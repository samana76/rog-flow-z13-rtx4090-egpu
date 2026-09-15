#include <KStatusNotifierItem>
#include <QApplication>
extern "C" {
void *egpu_tray_create(void *menu) {
 auto *item = new KStatusNotifierItem(QStringLiteral("gpd-egpu-tray"), qApp);
 item->setTitle(QStringLiteral("GPD eGPU"));
 item->setCategory(KStatusNotifierItem::Hardware);
 item->setStandardActionsEnabled(false);
 item->setContextMenu(static_cast<QMenu *>(menu));
 item->setIsMenu(true);
 item->setIconByName(QStringLiteral("video-display"));
 item->setStatus(KStatusNotifierItem::Active);
 return item;
}
void egpu_tray_status(void *p, const char *text, const char *icon) {
 auto *item = static_cast<KStatusNotifierItem *>(p);
 item->setToolTip(QString::fromUtf8(icon), QStringLiteral("GPD eGPU"), QString::fromUtf8(text));
 item->setIconByName(QString::fromUtf8(icon));
}
void egpu_tray_message(void *p, const char *title, const char *text) {
 static_cast<KStatusNotifierItem *>(p)->showMessage(QString::fromUtf8(title), QString::fromUtf8(text), QStringLiteral("video-display"));
}
}
