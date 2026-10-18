use ksni::{blocking::TrayMethods, menu, MenuItem};
use serde::Deserialize;
use std::io::{self, BufRead, Write};
use std::sync::{atomic::{AtomicBool, Ordering}, mpsc, Arc};
use std::time::{Duration, Instant};

#[derive(Clone, Deserialize)]
struct Row {
    label: String,
    action: Option<String>,
    enabled: bool,
    checked: bool,
    children: Vec<Row>,
}

#[derive(Clone, Deserialize)]
struct Snapshot {
    schema: u32,
    status: String,
    menu: Vec<Row>,
}

fn emit(value: serde_json::Value) {
    let mut output = io::stdout().lock();
    let _ = writeln!(output, "{}", value);
    let _ = output.flush();
}

fn items(rows: &[Row]) -> Vec<MenuItem<RouterMenu>> {
    rows.iter().map(|row| {
        if row.label.is_empty() { return MenuItem::Separator; }
        if !row.children.is_empty() {
            return menu::SubMenu {
                label: row.label.clone(), enabled: row.enabled,
                submenu: items(&row.children), ..Default::default()
            }.into();
        }
        let action = row.action.clone();
        menu::CheckmarkItem {
            label: row.label.clone(), enabled: row.enabled, checked: row.checked,
            activate: Box::new(move |_| {
                if let Some(id) = &action { emit(serde_json::json!({"action": id})); }
            }), ..Default::default()
        }.into()
    }).collect()
}

struct RouterMenu { snapshot: Snapshot, icon: String }
impl ksni::Tray for RouterMenu {
    const MENU_ON_ACTIVATE: bool = true;
    fn id(&self) -> String { "com.softwarecombined.router.menu".into() }
    fn title(&self) -> String { "SCG Router".into() }
    fn icon_name(&self) -> String { self.icon.clone() }
    fn tool_tip(&self) -> ksni::ToolTip {
        ksni::ToolTip { title: "SCG Router".into(), description: self.snapshot.status.clone(),
                       ..Default::default() }
    }
    fn menu(&self) -> Vec<MenuItem<Self>> { items(&self.snapshot.menu) }
    fn watcher_offline(&self, _: ksni::OfflineReason) -> bool {
        true
    }
}

fn report_host(connection: &mut Option<zbus::blocking::Connection>, previous: &mut Option<bool>) {
    if connection.is_none() { *connection = zbus::blocking::Connection::session().ok(); }
    let available = connection.as_ref().and_then(|bus| {
        zbus::blocking::Proxy::new(bus, "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
            "org.kde.StatusNotifierWatcher").ok()?.get_property::<bool>(
                "IsStatusNotifierHostRegistered").ok()
    });
    if available.is_none() { *connection = None; }
    let available = available.unwrap_or(false);
    if *previous != Some(available) {
        emit(serde_json::json!({"host": available}));
        *previous = Some(available);
    }
}

fn main() {
    let icon = match std::env::args().nth(1) { Some(value) => value, None => return };
    let (send, receive) = mpsc::sync_channel(2);
    let closed = Arc::new(AtomicBool::new(false));
    let input_closed = closed.clone();
    std::thread::spawn(move || {
        for line in io::stdin().lock().lines() {
            let line = match line { Ok(value) if value.len() <= 65536 => value, _ => break };
            if let Ok(value) = serde_json::from_str::<Snapshot>(&line) {
                if value.schema == 1 && send.send(value).is_err() { break; }
            }
        }
        input_closed.store(true, Ordering::Release);
    });
    let mut latest = match receive.recv() { Ok(value) => value, Err(_) => return };
    let (mut connection, mut previous) = (None, None);
    while !closed.load(Ordering::Acquire) {
        report_host(&mut connection, &mut previous);
        let tray = RouterMenu { snapshot: latest.clone(), icon: icon.clone() };
        match tray.spawn() {
            Ok(handle) => {
                let mut next_check = Instant::now();
                while !closed.load(Ordering::Acquire) && !handle.is_closed() {
                    if Instant::now() >= next_check {
                        report_host(&mut connection, &mut previous);
                        next_check = Instant::now() + Duration::from_secs(2);
                    }
                    if let Ok(value) = receive.recv_timeout(Duration::from_millis(500)) {
                        latest = value.clone();
                        handle.update(|tray| tray.snapshot = value);
                    }
                }
                handle.shutdown().wait();
            }
            Err(_) => {
                if let Ok(value) = receive.recv_timeout(Duration::from_secs(2)) { latest = value; }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    struct Watcher { host: Arc<AtomicBool>, registrations: Arc<AtomicUsize> }
    #[zbus::interface(name = "org.kde.StatusNotifierWatcher")]
    impl Watcher {
        fn register_status_notifier_item(&self, _service: &str) {
            self.registrations.fetch_add(1, Ordering::SeqCst);
        }
        #[zbus(property)]
        fn is_status_notifier_host_registered(&self) -> bool {
            self.host.load(Ordering::SeqCst)
        }
    }

    fn watcher(host: Arc<AtomicBool>, registrations: Arc<AtomicUsize>) -> zbus::blocking::Connection {
        zbus::blocking::connection::Builder::session().unwrap()
            .name("org.kde.StatusNotifierWatcher").unwrap()
            .serve_at("/StatusNotifierWatcher", Watcher { host, registrations }).unwrap()
            .build().unwrap()
    }

    #[test]
    #[ignore = "run under a private dbus-run-session"]
    fn detects_actual_host_loss_and_recovers_registration() {
        assert!(std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_some());
        let host = Arc::new(AtomicBool::new(false));
        let registrations = Arc::new(AtomicUsize::new(0));
        let server = watcher(host.clone(), registrations.clone());
        let (mut connection, mut previous) = (None, None);
        report_host(&mut connection, &mut previous);
        assert_eq!(previous, Some(false)); // A watcher alone is insufficient.
        host.store(true, Ordering::SeqCst);
        report_host(&mut connection, &mut previous);
        assert_eq!(previous, Some(true));
        let handle = RouterMenu { snapshot: Snapshot { schema: 1, status: "Running".into(), menu: vec![] },
                                  icon: "scg-router".into() }.spawn().unwrap();
        assert_eq!(registrations.load(Ordering::SeqCst), 1);
        host.store(false, Ordering::SeqCst);
        report_host(&mut connection, &mut previous);
        assert_eq!(previous, Some(false)); // The watcher remains owned.
        drop(server);
        host.store(true, Ordering::SeqCst);
        let _replacement = watcher(host.clone(), registrations.clone());
        let deadline = Instant::now() + Duration::from_secs(5);
        while registrations.load(Ordering::SeqCst) < 2 && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(registrations.load(Ordering::SeqCst) >= 2);
        report_host(&mut connection, &mut previous);
        assert_eq!(previous, Some(true));
        handle.shutdown().wait();
    }
}
