// 密语（MiYu）独立轻量卸载程序 —— 零额外依赖，原生编译（约 25 KB）
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace MiYuUninstaller
{
    internal static class Program
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        private static int Main(string[] args)
        {
            foreach (string a in args)
            {
                if (string.Equals(a, "--selftest", StringComparison.OrdinalIgnoreCase))
                {
                    return 0;
                }
            }
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new UninstallForm());
            return 0;
        }
    }

    internal sealed class UninstallForm : Form
    {
        private readonly string _appDir;
        private readonly string _selfPath;
        private readonly string _localDataDir;
        private readonly string _portableDataDir;

        private readonly CheckBox _chkApp;
        private readonly CheckBox _chkEasyTier;
        private readonly CheckBox _chkData;
        private readonly Label _lblStatus;
        private readonly ProgressBar _bar;
        private readonly Button _btnUninstall;
        private readonly Button _btnCancel;

        public UninstallForm()
        {
            _selfPath = Path.GetFullPath(Application.ExecutablePath);
            _appDir = Path.GetDirectoryName(_selfPath) ?? Environment.CurrentDirectory;
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            _localDataDir = Path.Combine(localApp, "MiYu");
            _portableDataDir = Path.Combine(_appDir, "MiYuData");

            Text = "密语（MiYu）· 卸载程序";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(490, 345);
            BackColor = Color.FromArgb(248, 250, 253);
            Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Regular);
            try { Icon = Icon.ExtractAssociatedIcon(_selfPath); } catch { }

            // 顶部标题条
            Panel header = new Panel
            {
                Dock = DockStyle.Top,
                Height = 76,
                BackColor = Color.White,
                Padding = new Padding(20, 14, 20, 12)
            };
            PictureBox pic = new PictureBox
            {
                Location = new Point(20, 16),
                Size = new Size(44, 44),
                SizeMode = PictureBoxSizeMode.Zoom
            };
            try
            {
                if (Icon != null) pic.Image = Icon.ToBitmap();
            }
            catch { }

            Label title = new Label
            {
                Text = "卸载 密语（MiYu）",
                Font = new Font("Microsoft YaHei UI", 13F, FontStyle.Bold),
                ForeColor = Color.FromArgb(24, 34, 51),
                Location = new Point(76, 15),
                AutoSize = true
            };
            Label sub = new Label
            {
                Text = "当前位置：" + TruncatePath(_appDir, 44),
                Font = new Font("Microsoft YaHei UI", 8.5F, FontStyle.Regular),
                ForeColor = Color.FromArgb(105, 118, 138),
                Location = new Point(76, 44),
                AutoSize = true
            };
            Panel sep = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 1,
                BackColor = Color.FromArgb(228, 234, 242)
            };
            header.Controls.Add(pic);
            header.Controls.Add(title);
            header.Controls.Add(sub);
            header.Controls.Add(sep);
            Controls.Add(header);

            // 选项卡片
            Panel card = new Panel
            {
                Location = new Point(20, 92),
                Size = new Size(450, 152),
                BackColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };

            long etBytes = GetDirSize(Path.Combine(_localDataDir, "easytier")) + GetDirSize(Path.Combine(_appDir, "easytier"));
            foreach (string pf in ProtectedEasyTierDirs()) etBytes += GetDirSize(pf);
            long dataBytes = GetDirSize(_localDataDir) + GetDirSize(_portableDataDir);

            _chkApp = new CheckBox
            {
                Text = "卸载密语主程序（MiYu.exe）、桌面/开始菜单快捷方式及自启项",
                Checked = true,
                Location = new Point(16, 18),
                Size = new Size(420, 26),
                ForeColor = Color.FromArgb(28, 39, 56)
            };
            _chkEasyTier = new CheckBox
            {
                Text = "清理 EasyTier 跨网联机内核与临时文件" + (etBytes > 0 ? string.Format("（约 {0}）", FormatSize(etBytes)) : ""),
                Checked = true,
                Location = new Point(16, 54),
                Size = new Size(420, 26),
                ForeColor = Color.FromArgb(28, 39, 56)
            };
            _chkData = new CheckBox
            {
                Text = "同时彻底清空聊天记录、账号、宠物与收藏（不可恢复）" + (dataBytes > 0 ? string.Format("（约 {0}）", FormatSize(dataBytes)) : ""),
                Checked = false,
                Location = new Point(16, 90),
                Size = new Size(420, 26),
                ForeColor = Color.FromArgb(185, 42, 42)
            };
            Label note = new Label
            {
                Text = "提示：默认保留本地加密聊天记录与账号，以后重新放入 MiYu.exe 仍可继续使用。",
                Font = new Font("Microsoft YaHei UI", 8.2F, FontStyle.Regular),
                ForeColor = Color.FromArgb(115, 126, 145),
                Location = new Point(18, 122),
                Size = new Size(416, 22)
            };

            card.Controls.Add(_chkApp);
            card.Controls.Add(_chkEasyTier);
            card.Controls.Add(_chkData);
            card.Controls.Add(note);
            Controls.Add(card);

            _lblStatus = new Label
            {
                Text = "请勾选要清理的项目，然后点击「开始卸载」。",
                Font = new Font("Microsoft YaHei UI", 8.8F, FontStyle.Regular),
                ForeColor = Color.FromArgb(80, 95, 118),
                Location = new Point(22, 254),
                Size = new Size(446, 22)
            };
            Controls.Add(_lblStatus);

            _bar = new ProgressBar
            {
                Location = new Point(20, 278),
                Size = new Size(450, 10),
                Style = ProgressBarStyle.Continuous,
                Value = 0
            };
            Controls.Add(_bar);

            _btnUninstall = new Button
            {
                Text = "开始卸载",
                Location = new Point(268, 298),
                Size = new Size(102, 34),
                BackColor = Color.FromArgb(220, 56, 56),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Cursor = Cursors.Hand
            };
            _btnUninstall.FlatAppearance.BorderSize = 0;
            _btnUninstall.Click += OnUninstallClick;

            _btnCancel = new Button
            {
                Text = "取消",
                Location = new Point(380, 298),
                Size = new Size(90, 34),
                BackColor = Color.FromArgb(236, 240, 246),
                ForeColor = Color.FromArgb(40, 50, 68),
                FlatStyle = FlatStyle.Flat,
                Cursor = Cursors.Hand
            };
            _btnCancel.FlatAppearance.BorderSize = 0;
            _btnCancel.Click += (s, e) => Close();

            Controls.Add(_btnUninstall);
            Controls.Add(_btnCancel);
        }

        private void OnUninstallClick(object sender, EventArgs e)
        {
            if (!_chkApp.Checked && !_chkEasyTier.Checked && !_chkData.Checked)
            {
                MessageBox.Show(this, "请至少勾选一项要清理的内容。", "密语卸载程序",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            string confirmMsg = _chkData.Checked
                ? "确定要卸载密语，并【彻底清空全部聊天记录、账号与萌宠数据】吗？\n\n此操作不可恢复！"
                : "确定要卸载密语吗？\n\n（你的本地聊天记录与账号数据将会保留）";

            if (MessageBox.Show(this, confirmMsg, "确认卸载 密语",
                MessageBoxButtons.YesNo,
                _chkData.Checked ? MessageBoxIcon.Warning : MessageBoxIcon.Question,
                MessageBoxDefaultButton.Button2) != DialogResult.Yes)
            {
                return;
            }

            _btnUninstall.Enabled = false;
            _btnCancel.Enabled = false;
            _chkApp.Enabled = false;
            _chkEasyTier.Enabled = false;
            _chkData.Enabled = false;

            List<string> done = new List<string>();
            List<string> warns = new List<string>();

            // 1. 关闭正在运行的密语与 EasyTier 进程
            UpdateProgress(20, "正在关闭运行中的密语与跨网内核进程…");
            StopProcessByName("MiYu");
            StopProcessByName("easytier-core");
            StopProcessByName("easytier-cli");
            Thread.Sleep(500);

            // 2. 清理 EasyTier 内核
            if (_chkEasyTier.Checked || _chkData.Checked)
            {
                UpdateProgress(45, "正在清理 EasyTier 跨网内核与临时文件…");
                bool anyEt = false;
                anyEt |= SafeDeleteDir(Path.Combine(_localDataDir, "easytier"), warns);
                anyEt |= SafeDeleteDir(Path.Combine(_appDir, "easytier"), warns);
                // 3.9.4 起内核校验后运行在 C:\Program Files\MiYu-EasyTier(只有管理员能写),卸载程序本身带管理员权限
                foreach (string pf in ProtectedEasyTierDirs()) anyEt |= SafeDeleteDir(pf, warns);
                if (anyEt) done.Add("已清理 EasyTier 跨网内核");
            }

            // 3. 清空用户数据（可选）
            if (_chkData.Checked)
            {
                UpdateProgress(65, "正在清空本地聊天记录、账号与收藏数据…");
                bool anyData = false;
                anyData |= SafeDeleteDir(_localDataDir, warns);
                anyData |= SafeDeleteDir(_portableDataDir, warns);
                if (anyData) done.Add("已彻底清空本地数据与聊天记录");
            }

            // 4. 卸载主程序、快捷方式与自启项
            bool deleteSelf = false;
            if (_chkApp.Checked)
            {
                UpdateProgress(85, "正在移除 MiYu.exe、快捷方式与自启项…");
                string[] exes = { "MiYu.exe", "MiYu.exe.old", "MiYu.exe.new", "MiYu.signed.exe" };
                bool removedExe = false;
                foreach (string name in exes)
                {
                    string p = Path.Combine(_appDir, name);
                    if (File.Exists(p))
                    {
                        if (SafeDeleteFile(p, warns)) removedExe = true;
                    }
                }
                RemoveShortcutsAndStartup();
                if (removedExe) done.Add("已移除 MiYu.exe 主程序");
                done.Add("已清理快捷方式与自启项");
                deleteSelf = true;
            }

            UpdateProgress(100, "卸载完成！");

            string summary = "✅ 密语卸载已完成！\n\n"
                + (done.Count > 0 ? "• " + string.Join("\n• ", done) : "未发现需要移除的文件。");
            if (!_chkData.Checked)
            {
                summary += "\n\n（已为你保留本地加密聊天记录与账号数据）";
            }
            if (warns.Count > 0)
            {
                summary += "\n\n部分文件被占用未能立即移除：\n" + string.Join("\n", warns);
            }

            MessageBox.Show(this, summary, "密语卸载完成", MessageBoxButtons.OK, MessageBoxIcon.Information);

            if (deleteSelf)
            {
                ScheduleSelfDelete(_selfPath);
            }
            Close();
        }

        private void UpdateProgress(int val, string msg)
        {
            _bar.Value = Math.Max(0, Math.Min(100, val));
            _lblStatus.Text = msg;
            Application.DoEvents();
        }

        private static void StopProcessByName(string procName)
        {
            try
            {
                foreach (Process p in Process.GetProcessesByName(procName))
                {
                    try
                    {
                        if (p.Id == Process.GetCurrentProcess().Id) continue;
                        try { p.CloseMainWindow(); } catch { }
                        if (!p.WaitForExit(1200))
                        {
                            p.Kill();
                            p.WaitForExit(1500);
                        }
                    }
                    catch { }
                    finally
                    {
                        try { p.Dispose(); } catch { }
                    }
                }
            }
            catch { }
        }

        private static bool SafeDeleteFile(string path, List<string> warns)
        {
            for (int i = 0; i < 4; i++)
            {
                try
                {
                    if (!File.Exists(path)) return true;
                    File.SetAttributes(path, FileAttributes.Normal);
                    File.Delete(path);
                    return true;
                }
                catch
                {
                    Thread.Sleep(250);
                }
            }
            warns.Add(path);
            return false;
        }

        private static List<string> ProtectedEasyTierDirs()
        {
            List<string> dirs = new List<string>();
            foreach (Environment.SpecialFolder sf in new Environment.SpecialFolder[] { Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86 })
            {
                try
                {
                    string root = Environment.GetFolderPath(sf);
                    if (string.IsNullOrEmpty(root)) continue;
                    string d = Path.Combine(root, "MiYu-EasyTier");
                    if (!dirs.Contains(d)) dirs.Add(d);
                }
                catch { }
            }
            return dirs;
        }

        private static bool SafeDeleteDir(string dir, List<string> warns)
        {
            if (!Directory.Exists(dir)) return false;
            for (int i = 0; i < 4; i++)
            {
                try
                {
                    foreach (string f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                    {
                        try { File.SetAttributes(f, FileAttributes.Normal); } catch { }
                    }
                    Directory.Delete(dir, true);
                    return true;
                }
                catch
                {
                    Thread.Sleep(250);
                }
            }
            warns.Add(dir);
            return false;
        }

        private static void RemoveShortcutsAndStartup()
        {
            string[] folders =
            {
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs"),
                Environment.GetFolderPath(Environment.SpecialFolder.Startup)
            };
            string[] names = { "MiYu.lnk", "密语.lnk", "密语 MiYu.lnk" };
            foreach (string dir in folders)
            {
                if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) continue;
                foreach (string n in names)
                {
                    string p = Path.Combine(dir, n);
                    try { if (File.Exists(p)) File.Delete(p); } catch { }
                }
            }
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true))
                {
                    if (key != null)
                    {
                        if (key.GetValue("MiYu") != null) key.DeleteValue("MiYu", false);
                        if (key.GetValue("密语") != null) key.DeleteValue("密语", false);
                    }
                }
            }
            catch { }
        }

        private static void ScheduleSelfDelete(string exePath)
        {
            try
            {
                string escaped = exePath.Replace("\"", "\"\"");
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = string.Format("/c ping 127.0.0.1 -n 2 >nul & del /f /q \"{0}\"", escaped),
                    WindowStyle = ProcessWindowStyle.Hidden,
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                Process.Start(psi);
            }
            catch { }
        }

        private static long GetDirSize(string dir)
        {
            if (!Directory.Exists(dir)) return 0;
            long total = 0;
            try
            {
                foreach (string f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                {
                    try { total += new FileInfo(f).Length; } catch { }
                }
            }
            catch { }
            return total;
        }

        private static string FormatSize(long bytes)
        {
            if (bytes >= 1048576L) return string.Format("{0:0.1} MB", bytes / 1048576.0);
            if (bytes >= 1024L) return string.Format("{0:0} KB", bytes / 1024.0);
            return bytes + " B";
        }

        private static string TruncatePath(string p, int maxLen)
        {
            if (string.IsNullOrEmpty(p) || p.Length <= maxLen) return p;
            return p.Substring(0, 14) + "…" + p.Substring(p.Length - (maxLen - 16));
        }
    }
}
