import importlib.util
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'code/tray/egpu-tray.py'
s=importlib.util.spec_from_file_location('tray',p); t=importlib.util.module_from_spec(s);s.loader.exec_module(t)
assert t.telemetry_text('35, 123.45\n')=='GPU: 35%   |   Power: 123.5 W'
assert t.telemetry_text('0, 40')=='GPU: 0%   |   Power: 40.0 W'
assert t.telemetry_text('[N/A], [Not Supported]')=='GPU: N/A   |   Power: N/A'
assert t.telemetry_text('nan, -3')=='GPU: N/A   |   Power: N/A'
try:t.telemetry_text('garbage')
except ValueError:pass
else:raise AssertionError('Malformed response accepted')
x=SimpleNamespace(refresh=Mock(),busy=False,current=('0000:63:00.0',),safe=None,showMessage=Mock(),telemetry=object(),cancel_telemetry=Mock(),start_disconnect_helper=Mock())
t.Tray.disconnect(x)
assert x.busy and x.pending_disconnect
x.cancel_telemetry.assert_called_once();x.start_disconnect_helper.assert_not_called()
proc=SimpleNamespace(readAllStandardOutput=lambda:b'30, 100',deleteLater=Mock())
x.telemetry=proc;x.telemetry_timeout=SimpleNamespace(stop=Mock());x.telemetry_target=x.current
x.usage=SimpleNamespace(setText=Mock())
t.Tray.telemetry_finished(x,proc,0,t.QProcess.ExitStatus.NormalExit)
x.start_disconnect_helper.assert_called_once();x.usage.setText.assert_not_called();assert x.telemetry is None
# No fresh query while disconnecting or while ready to unplug.
for busy,safe in [(True,None),(False,x.current)]:
 x.busy=busy;x.safe=safe
 with patch.object(t,'devices',side_effect=AssertionError('Unexpected polling')):t.Tray.poll_telemetry(x)
print('PASS: telemetry parsing, unsupported values, eject query-reaping order, polling suppression')
