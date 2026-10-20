using System;
using System.Collections.Generic;
using System.Drawing;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

// Native presentation only. No settings, keys, network calls or process launching.
internal sealed class RouterMenu : ApplicationContext {
    readonly NotifyIcon icon = new NotifyIcon();
    readonly Control dispatcher = new Control();
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 65536 };
    readonly string iconPath;
    [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr value);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

    RouterMenu(string path) {
        iconPath = path;
        dispatcher.CreateControl();
        var handle = dispatcher.Handle;
        RefreshIcon();
        icon.Text = "SCG Router";
        icon.Visible = true;
        icon.MouseClick += (s, e) => {
            if (e.Button != MouseButtons.Left || icon.ContextMenuStrip == null) return;
            // Take the right-click path: NotifyIcon makes its window the foreground
            // first, so clicking elsewhere or pressing Escape dismisses the menu.
            var show = typeof(NotifyIcon).GetMethod("ShowContextMenu",
                BindingFlags.Instance | BindingFlags.NonPublic);
            if (show != null) show.Invoke(icon, null);
            else icon.ContextMenuStrip.Show(Cursor.Position);
        };
        SystemEvents.UserPreferenceChanged += PreferencesChanged;
        var reader = new Thread(ReadInput) { IsBackground = true };
        reader.Start();
    }

    void PreferencesChanged(object sender, UserPreferenceChangedEventArgs args) {
        if (!dispatcher.IsDisposed) dispatcher.BeginInvoke((Action)RefreshIcon);
    }

    void RefreshIcon() {
        bool light = false;
        using (var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")) {
            light = key != null && Convert.ToInt32(key.GetValue("SystemUsesLightTheme", 0)) != 0;
        }
        Color foreground = SystemInformation.HighContrast ? SystemColors.WindowText :
                           (light ? Color.Black : Color.White);
        using (var image = new Bitmap(iconPath))
        using (var pixels = new Bitmap(image, new Size(32, 32))) {
            for (int y = 0; y < 32; y++) for (int x = 0; x < 32; x++) {
                var value = pixels.GetPixel(x, y);
                int white = Math.Min(value.R, Math.Min(value.G, value.B));
                pixels.SetPixel(x, y, Color.FromArgb((255 - white) * value.A / 255, foreground));
            }
            IntPtr native = pixels.GetHicon();
            var replacement = (Icon)Icon.FromHandle(native).Clone();
            DestroyIcon(native);
            var previous = icon.Icon;
            icon.Icon = replacement;
            if (previous != null) previous.Dispose();
        }
    }

    void Emit(string action) {
        Console.WriteLine(json.Serialize(new Dictionary<string, object> { { "action", action } }));
        Console.Out.Flush();
    }

    ToolStripItem[] Build(object[] rows) {
        var result = new List<ToolStripItem>();
        foreach (Dictionary<string, object> row in rows) {
            string label = Convert.ToString(row["label"]);
            if (label.Length == 0) { result.Add(new ToolStripSeparator()); continue; }
            var entry = new ToolStripMenuItem(label) {
                Enabled = Convert.ToBoolean(row["enabled"]),
                Checked = Convert.ToBoolean(row["checked"])
            };
            var children = row["children"] as object[];
            if (children != null && children.Length > 0) entry.DropDownItems.AddRange(Build(children));
            else if (row["action"] != null) {
                string action = Convert.ToString(row["action"]);
                entry.Click += (s, e) => Emit(action);
            }
            result.Add(entry);
        }
        return result.ToArray();
    }

    void ReadInput() {
        try {
            string line;
            while ((line = Console.ReadLine()) != null) {
                if (line.Length > 65536) break;
                var doc = json.DeserializeObject(line) as Dictionary<string, object>;
                if (doc == null || Convert.ToInt32(doc["schema"]) != 1) continue;
                dispatcher.BeginInvoke((Action)(() => Update(doc)));
            }
        } catch (Exception) { }
        if (!dispatcher.IsDisposed) dispatcher.BeginInvoke((Action)ExitThread);
    }

    void Update(Dictionary<string, object> doc) {
        var menu = icon.ContextMenuStrip;
        if (menu == null) {
            menu = new ContextMenuStrip();
            menu.Opening += (s, e) => Emit("refresh");
            icon.ContextMenuStrip = menu;
        }
        // One strip for the helper's lifetime, refreshed in place: an open menu shows
        // the new state at once, and no popup is disposed while it is showing.
        var previous = new ToolStripItem[menu.Items.Count];
        menu.Items.CopyTo(previous, 0);
        menu.SuspendLayout();
        menu.Items.Clear();
        menu.Items.AddRange(Build((object[])doc["menu"]));
        menu.ResumeLayout();
        foreach (var item in previous) item.Dispose();
        string text = "SCG Router: " + Convert.ToString(doc["status"]);
        icon.Text = text.Substring(0, Math.Min(text.Length, 63));
    }

    protected override void ExitThreadCore() {
        SystemEvents.UserPreferenceChanged -= PreferencesChanged;
        if (icon.ContextMenuStrip != null) icon.ContextMenuStrip.Close();
        icon.Visible = false;
        icon.Dispose();
        dispatcher.Dispose();
        base.ExitThreadCore();
    }

    [STAThread] static void Main(string[] args) {
        if (args.Length != 1) return;
        SetProcessDPIAware();
        Application.EnableVisualStyles();
        Application.Run(new RouterMenu(args[0]));
    }
}
