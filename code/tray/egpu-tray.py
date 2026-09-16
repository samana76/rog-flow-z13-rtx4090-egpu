#!/usr/bin/python3
"""User-session tray; only the existing root helper may change GPU state."""
import sys
import os
import ctypes
import math
import shiboken6
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QTimer
from PySide6.QtGui import QAction, QIcon, QCursor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QMessageBox
from PySide6.QtNetwork import QLocalServer, QLocalSocket

HELPER = '/usr/local/libexec/gpd-egpu-eject'

def devices(root=Path('/sys/bus/pci/devices')):
    found = []
    for p in root.glob('*'):
        try:
            if ((p/'vendor').read_text().strip() == '0x10de' and
                (p/'device').read_text().strip() == '0x2684' and
                (p/'class').read_text().strip().startswith('0x03')):
                found.append(p.name)
        except OSError:
            continue
    return tuple(sorted(found))

def telemetry_text(output):
    fields = output.strip().split(',')
    if len(fields) != 2:
        raise ValueError('Unexpected telemetry response')
    def number(raw, percent=False):
        try:
            value = float(raw.strip())
        except ValueError:
            return 'N/A'
        if not math.isfinite(value) or value < 0 or (percent and value > 100):
            return 'N/A'
        return f'{value:.0f}%' if percent else f'{value:.1f} W'
    return 'GPU: ' + number(fields[0], True) + '   |   Power: ' + number(fields[1])


def succeeded(code, normal, output):
    return normal and code == 0 and 'READY TO UNPLUG:' in output

class Tray(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.busy = False
        self.safe = None
        self.current = ()
        self.last_output = ''
        self.process = None
        self.menu = QMenu()
        self.status = self.menu.addAction('GPD RTX 4090')
        self.status.setEnabled(False)
        self.usage = self.menu.addAction('GPU: —   |   Power: —')
        self.usage.setEnabled(False)
        self.menu.addSeparator()
        self.telemetry = None
        self.pending_disconnect = False
        self.telemetry_timeout = QTimer(self)
        self.telemetry_timeout.setSingleShot(True)
        self.telemetry_timeout.timeout.connect(self.cancel_telemetry)
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self.poll_telemetry)
        self.telemetry_timer.start(3000)
        self.menu.aboutToShow.connect(self.poll_telemetry)
        self.eject = self.menu.addAction('Disconnect eGPU safely')
        self.eject.triggered.connect(self.disconnect)
        self.details = self.menu.addAction('Last disconnect result')
        self.details.triggered.connect(self.show_result)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction('Quit tray icon')
        self.quit_action.triggered.connect(app.quit)
        self.native = ctypes.CDLL(str(Path(__file__).with_name('native-tray.so')))
        self.native.egpu_tray_create.argtypes = [ctypes.c_void_p]
        self.native.egpu_tray_create.restype = ctypes.c_void_p
        self.native.egpu_tray_status.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.native.egpu_tray_status.restype = None
        self.native.egpu_tray_message.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.native.egpu_tray_message.restype = None
        self.item = self.native.egpu_tray_create(shiboken6.getCppPointer(self.menu)[0])
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()
        self.poll_telemetry()
        app.aboutToQuit.connect(self.cancel_telemetry)

    def showMessage(self, title, text, *unused):
        self.native.egpu_tray_message(self.item, title.encode(), text.encode())

    def refresh(self):
        current = devices()
        if current != self.current:
            self.safe = None
            self.usage.setText('GPU: —   |   Power: —')
            self.cancel_telemetry()
        self.current = current
        if self.busy:
            state = 'Disconnecting — keep cable connected'
        elif not current:
            state = 'GPD eGPU disconnected'
        elif self.safe == current:
            state = 'GPD eGPU — safe to unplug'
        else:
            state = 'GPD eGPU connected'
        if self.busy or not current or self.safe == current:
            self.usage.setText('GPU: —   |   Power: —')
        self.status.setText(state)
        icon = 'media-eject' if self.safe == current and current else 'video-display'
        self.native.egpu_tray_status(self.item, state.encode(), icon.encode())
        self.eject.setEnabled(bool(current) and not self.busy and self.safe != current)
        self.quit_action.setEnabled(not self.busy)

    def cancel_telemetry(self):
        if self.telemetry is not None and self.telemetry.state() != QProcess.ProcessState.NotRunning:
            self.telemetry.kill()

    def poll_telemetry(self):
        if self.telemetry is not None or self.busy or self.safe == self.current:
            return
        current = devices()
        if len(current) != 1:
            self.usage.setText('GPU: —   |   Power: —')
            return
        gpu = Path('/sys/bus/pci/devices') / current[0]
        if (gpu/'driver').resolve().name != 'nvidia' or not Path('/sys/module/nvidia').exists():
            self.usage.setText('GPU: driver inactive   |   Power: —')
            return
        process = QProcess(self)
        self.telemetry = process
        self.telemetry_target = current
        process.finished.connect(lambda code, status: self.telemetry_finished(process, code, status))
        process.errorOccurred.connect(lambda error: self.telemetry_failed(process, error))
        process.start('/usr/bin/nvidia-smi', ['-i', current[0], '--query-gpu=utilization.gpu,power.draw', '--format=csv,noheader,nounits'])
        self.telemetry_timeout.start(2000)

    def telemetry_failed(self, process, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.telemetry_finished(process, -1, QProcess.ExitStatus.CrashExit)

    def telemetry_finished(self, process, code, status):
        if self.telemetry is not process:
            return
        self.telemetry_timeout.stop()
        output = bytes(process.readAllStandardOutput()).decode(errors='replace')
        self.telemetry = None
        process.deleteLater()
        if not self.busy and self.safe != self.current and devices() == self.telemetry_target:
            try:
                if code != 0 or status != QProcess.ExitStatus.NormalExit:
                    raise ValueError('Query failed')
                self.usage.setText(telemetry_text(output))
            except ValueError:
                self.usage.setText('GPU: unavailable   |   Power: unavailable')
        if self.pending_disconnect:
            self.pending_disconnect = False
            self.start_disconnect_helper()

    def disconnect(self):
        self.refresh()
        if self.busy or not self.current or self.safe == self.current:
            return
        self.busy = True
        self.target = self.current
        self.last_output = ''
        self.refresh()
        self.showMessage('Disconnecting eGPU', 'Keep the cable connected while the display and driver are released.')
        # Reap our NVML client before the helper inspects clients or unloads modules.
        if self.telemetry is not None:
            self.pending_disconnect = True
            self.cancel_telemetry()
        else:
            self.start_disconnect_helper()

    def start_disconnect_helper(self):
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start('/usr/bin/pkexec', [HELPER])

    def read_output(self):
        self.last_output = (self.last_output + bytes(self.process.readAllStandardOutput()).decode(errors='replace'))[-16000:]

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.last_output += '\nCould not start the disconnect helper.'
            self.finished(-1, QProcess.ExitStatus.CrashExit)

    def finished(self, code, status):
        if not self.busy:
            return
        self.read_output()
        ok = succeeded(code, status == QProcess.ExitStatus.NormalExit, self.last_output)
        self.busy = False
        self.current = devices()
        if ok and self.current == self.target:
            self.safe = self.current
            self.showMessage('Safe to unplug eGPU', 'The NVIDIA drivers have unloaded. You may now unplug the USB4 cable.')
        else:
            self.showMessage('eGPU disconnect stopped', 'Keep the cable connected. Open “Last disconnect result” for details.', QSystemTrayIcon.MessageIcon.Warning)
        self.refresh()

    def show_result(self):
        QMessageBox.information(None, 'eGPU disconnect result', self.last_output or 'No disconnect requested from this tray session.')

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('GPD eGPU')
    app.setQuitOnLastWindowClosed(False)
    if '--smoke-test' in sys.argv:
        tray = Tray(app)
        QTimer.singleShot(200, app.quit)
        app.exec()
        return
    socket = QLocalSocket()
    name = 'gpd-egpu-tray-EGPU_USER'
    socket.connectToServer(name)
    if socket.waitForConnected(300):
        return
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        raise SystemExit('Cannot acquire tray instance socket')
    tray = Tray(app)
    if '--smoke-test' in sys.argv:
        QTimer.singleShot(1000, app.quit)
    app.exec()

if __name__ == '__main__':
    main()
