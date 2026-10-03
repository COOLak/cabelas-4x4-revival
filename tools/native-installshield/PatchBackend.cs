// Windowless x86 command-line backend; never launches the game or a wizard.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace Cabela4x4Patch121 {
    public sealed class PatchFailure : Exception {
        public readonly int Code;
        public PatchFailure(int code, string message) : base(message) { Code = code; }
    }
    public sealed class Build {
        public readonly string Language, Source, Patched;
        public readonly int Size;
        public Build(string language, int size, string source, string patched) {
            Language = language; Size = size; Source = source; Patched = patched;
        }
    }
    public static class Backend {
        public const string Tool = "Cabela4x4PatchBackend";
        public const string Target = "4x4 Adventure.exe";
        static readonly Build[] Builds = {
            new Build("en", 749568,
                "e9c5d3932dc87accd8a1d94a264de1badbe7edac73afaf1fa78181a30c624d1c",
                "9bdb9bfaa4d91f12bc81c0db1a05765c03538fb81f0a523c978733902ba2d3c6"),
            new Build("und", 757760,
                "ab517697d459912a924f8502b1be5b38d69c3bd4e8a3011689c5eca16077f765",
                "a54624101f8b04ed5539703ea558705483fc06974c1ca00eaf0964726d408faf")
        };
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

        [StructLayout(LayoutKind.Sequential)] struct FileInfo {
            public uint Attributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
            public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct ProcessEntry {
            public uint Size, Usage, Pid; public UIntPtr DefaultHeap; public uint Module;
            public uint Threads, ParentPid; public int Priority; public uint Flags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string Name;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateFileW(string path,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(IntPtr handle,out FileInfo info);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateToolhelp32Snapshot(uint flags,uint pid);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool Process32FirstW(IntPtr handle,ref ProcessEntry entry);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool Process32NextW(IntPtr handle,ref ProcessEntry entry);
        [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageNameW(IntPtr handle,uint flags,StringBuilder text,ref uint size);

        public static string Digest(byte[] data) {
            using (SHA256 sha = SHA256.Create()) {
                return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
            }
        }
        static string DirectoryPath(string path, bool mustExist) {
            string full = Path.GetFullPath(path);
            DirectoryInfo cursor = new DirectoryInfo(full);
            while (cursor != null) {
                if (File.Exists(cursor.FullName)) throw new PatchFailure(13, "A directory component is a file.");
                if (cursor.Exists && (cursor.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new PatchFailure(13, "Reparse-point directories are unsupported.");
                cursor = cursor.Parent;
            }
            if (mustExist && !Directory.Exists(full)) throw new PatchFailure(13, "The selected game directory does not exist.");
            return full.Length == Path.GetPathRoot(full).Length ? full : full.TrimEnd(Path.DirectorySeparatorChar);
        }
        static string SafeFile(string directory, string name, bool mustExist) {
            string parent = DirectoryPath(directory, mustExist);
            if (Path.GetFileName(name) != name || name.IndexOf(':') >= 0)
                throw new PatchFailure(13, "The backend requires a plain filename.");
            string path = Path.Combine(parent, name);
            if (Directory.Exists(path)) throw new PatchFailure(13, "Expected a regular file.");
            if (File.Exists(path)) {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new PatchFailure(13, "Reparse-point files are unsupported.");
                IntPtr handle = CreateFileW(path, 0, 7, IntPtr.Zero, 3, 0x00200000, IntPtr.Zero);
                if (handle == new IntPtr(-1)) throw new IOException("Cannot inspect file identity.", new Win32Exception(Marshal.GetLastWin32Error()));
                try {
                    FileInfo info;
                    if (!GetFileInformationByHandle(handle, out info)) throw new IOException("Cannot inspect link count.");
                    if (info.Links != 1) throw new PatchFailure(13, "Hard-linked files are unsupported.");
                } finally { CloseHandle(handle); }
            } else if (mustExist) throw new PatchFailure(12, "A required executable or backup is missing.");
            return path;
        }
        static byte[] Read(string path) {
            using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                if (stream.Length > 2 * 1024 * 1024) throw new PatchFailure(10, "The executable size is unsupported.");
                byte[] result = new byte[checked((int)stream.Length)]; int done = 0;
                while (done < result.Length) {
                    int got = stream.Read(result, done, result.Length - done);
                    if (got == 0) throw new IOException("The file changed while reading.");
                    done += got;
                }
                return result;
            }
        }
        static Build Recognize(byte[] data, string identity) {
            foreach (Build build in Builds)
                if (data.Length == build.Size && (identity == build.Source || identity == build.Patched)) return build;
            throw new PatchFailure(10, "Unsupported or modified executable. No executable was changed.");
        }
        static void GameClosed(string root) {
            string[] names = { Target, "4x4 Launcher.exe", "4x4 Setup.exe" };
            IntPtr snapshot = CreateToolhelp32Snapshot(2, 0);
            if (snapshot == new IntPtr(-1)) throw new PatchFailure(11, "Cannot check running game processes.");
            try {
                ProcessEntry entry = new ProcessEntry(); entry.Size = (uint)Marshal.SizeOf(typeof(ProcessEntry));
                bool more = Process32FirstW(snapshot, ref entry);
                while (more) {
                    foreach (string name in names) if (String.Equals(name, entry.Name, StringComparison.OrdinalIgnoreCase)) {
                        IntPtr process = OpenProcess(0x1000, false, entry.Pid);
                        if (process == IntPtr.Zero) throw new PatchFailure(11, "Cannot identify a running game process.");
                        try {
                            StringBuilder text = new StringBuilder(32768); uint size = (uint)text.Capacity;
                            if (!QueryFullProcessImageNameW(process, 0, text, ref size))
                                throw new PatchFailure(11, "Cannot identify a running game process.");
                            if (String.Equals(text.ToString(), Path.Combine(root, name), StringComparison.OrdinalIgnoreCase))
                                throw new PatchFailure(11, "Close Adventure, Setup and Launcher in the selected folder first.");
                        } finally { CloseHandle(process); }
                    }
                    more = Process32NextW(snapshot, ref entry);
                }
                if (Marshal.GetLastWin32Error() != 18) throw new PatchFailure(11, "Process enumeration did not finish safely.");
            } finally { CloseHandle(snapshot); }
        }
        static int ChecksumOffset(byte[] data) {
            if (data.Length < 64 || data[0] != 77 || data[1] != 90) throw new PatchFailure(15, "Invalid MZ header.");
            int pe = checked((int)BitConverter.ToUInt32(data, 60));
            if (pe < 64 || pe > data.Length - 24 || data[pe] != 80 || data[pe+1] != 69 || data[pe+2] != 0 || data[pe+3] != 0)
                throw new PatchFailure(15, "Invalid PE header.");
            int optional = pe + 24, optionalSize = BitConverter.ToUInt16(data, pe + 20);
            if (optionalSize < 68 || optional + optionalSize > data.Length) throw new PatchFailure(15, "Truncated PE optional header.");
            ushort magic = BitConverter.ToUInt16(data, optional);
            if (magic != 0x10b && magic != 0x20b) throw new PatchFailure(15, "Unsupported PE optional header.");
            return optional + 64;
        }
        public static uint Checksum(byte[] data) {
            int ignored = ChecksumOffset(data); ulong total = 0;
            for (int offset=0; offset<data.Length; offset+=2) {
                if (offset >= ignored && offset < ignored+4) continue;
                uint word = data[offset]; if (offset+1 < data.Length) word |= (uint)data[offset+1] << 8;
                total += word; total = (total & 65535) + (total >> 16);
            }
            total = (total & 65535) + (total >> 16);
            return (uint)((total & 65535) + (ulong)data.Length);
        }
        static byte[] Patched(byte[] original, Build build) {
            byte[] data = (byte[])original.Clone();
            foreach (int offset in new int[] { 0xd2d5, 0xd2da }) {
                if (data[offset] != 0x7f) throw new PatchFailure(15, "Unexpected original branch instruction.");
                data[offset] = 0x7d;
            }
            Array.Copy(BitConverter.GetBytes(Checksum(data)), 0, data, ChecksumOffset(data), 4);
            if (Digest(data) != build.Patched) throw new PatchFailure(15, "The patch does not match the expected complete-file hash.");
            return data;
        }
        static void WriteNew(string path, byte[] data) {
            using (FileStream stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                stream.Write(data, 0, data.Length); stream.Flush(true);
            }
        }
        static void AtomicReplace(string path, byte[] output, string expectedBefore, string root) {
            string temp = SafeFile(Path.GetDirectoryName(path), ".cabela4x4-" + Guid.NewGuid().ToString("N") + ".tmp", false);
            try {
                WriteNew(temp, output);
                if (Digest(Read(temp)) != Digest(output)) throw new PatchFailure(15, "Staged output verification failed.");
                GameClosed(root);
                SafeFile(Path.GetDirectoryName(path), Path.GetFileName(path), true);
                if (Digest(Read(path)) != expectedBefore) throw new PatchFailure(10, "The selected executable changed before commit.");
                File.Replace(temp, path, null);
                if (Digest(Read(path)) != Digest(output)) throw new PatchFailure(15, "Installed output verification failed; the verified backup is retained.");
            } finally { if (File.Exists(temp)) File.Delete(temp); }
        }
        static Dictionary<string,object> Report(string action) {
            return new Dictionary<string,object> { {"tool",Tool}, {"patch_version","1.2.1"}, {"action",action}, {"process_architecture",IntPtr.Size==4 ? "x86" : "x64"}, {"changed",false} };
        }
        public static int Execute(string action, string gameDirectory, out Dictionary<string,object> report) {
            report = Report(action);
            try {
                if (action != "apply" && action != "verify" && action != "rollback") throw new PatchFailure(64, "Unknown backend operation.");
                string root = DirectoryPath(gameDirectory, true); report["game_dir"] = root; GameClosed(root);
                string target = SafeFile(root, Target, true); byte[] original = Read(target); string identity = Digest(original);
                Build build = Recognize(original, identity); bool installed = identity == build.Patched;
                report["language"] = build.Language; report["before_sha256"] = identity;
                report["state"] = installed ? "patched" : "original";
                if (action == "verify") { report["status"] = installed ? "verified_patched" : "verified_original"; report["exit_code"] = installed ? 0 : 20; return installed ? 0 : 20; }
                string backupDir = DirectoryPath(Path.Combine(root, "cabela4x4-patch-1.2.1-backups", build.Source), false);
                string backup = SafeFile(backupDir, Target, false); report["backup_file"] = backup;
                if (File.Exists(backup) && Digest(Read(backup)) != build.Source) throw new PatchFailure(12, "The existing original backup is modified or belongs to another build.");
                if ((action == "apply" && installed) || (action == "rollback" && !installed)) {
                    report["status"] = installed ? "already_patched" : "already_original"; report["after_sha256"] = identity; report["exit_code"] = 0; return 0;
                }
                byte[] output;
                if (action == "apply") {
                    output = Patched(original, build);
                    if (!File.Exists(backup)) {
                        Directory.CreateDirectory(backupDir); backup = SafeFile(backupDir, Target, false);
                        WriteNew(backup, original);
                    }
                    if (Digest(Read(backup)) != build.Source) throw new PatchFailure(12, "Original backup verification failed.");
                } else {
                    backup = SafeFile(backupDir, Target, true); output = Read(backup);
                    if (Digest(output) != build.Source) throw new PatchFailure(12, "Rollback backup verification failed.");
                }
                AtomicReplace(target, output, identity, root);
                report["changed"] = true; report["after_sha256"] = Digest(output);
                report["state"] = action == "apply" ? "patched" : "original";
                report["status"] = action == "apply" ? "applied" : "rolled_back"; report["exit_code"] = 0; return 0;
            } catch (PatchFailure failure) {
                report["status"]="refused"; report["error"]=failure.Message; report["exit_code"]=failure.Code; return failure.Code;
            } catch (Exception failure) {
                report["status"]="error"; report["error"]=failure.Message; report["exit_code"]=14; return 14;
            }
        }
        public static string ReportPath(string destination, bool ini) {
            string path=Path.GetFullPath(destination);
            DirectoryPath(Path.GetDirectoryName(path),true);
            SafeFile(Path.GetDirectoryName(path),Path.GetFileName(path),false);
            string extension=ini ? ".ini" : ".json";
            if (!String.Equals(Path.GetExtension(path),extension,StringComparison.OrdinalIgnoreCase)) throw new PatchFailure(13,"Report filename must end in " + extension + ".");
            if (File.Exists(path)) {
                bool ours=false;
                try {
                    string existingText=File.ReadAllText(path);
                    if (ini) ours=existingText.StartsWith("[PatchResult]"+Environment.NewLine+"tool="+Tool+Environment.NewLine,StringComparison.Ordinal);
                    else {
                        Dictionary<string,object> existing=Json.Deserialize<Dictionary<string,object>>(existingText);
                        object marker; ours=existing!=null && existing.TryGetValue("tool",out marker) && Object.Equals(marker,Tool);
                    }
                } catch (Exception) { }
                if (!ours) throw new PatchFailure(13,"Refusing to overwrite an unrelated report file.");
            }
            return path;
        }
        public static void WriteReport(string destination, Dictionary<string,object> report) {
            string path=ReportPath(destination,false);
            File.WriteAllText(path,Json.Serialize(report)+Environment.NewLine,new UTF8Encoding(false));
        }
        static string IniValue(Dictionary<string,object> report,string key) {
            object value;
            string text=report.TryGetValue(key,out value) ? Convert.ToString(value,System.Globalization.CultureInfo.InvariantCulture) : "";
            return text.Replace("\r"," ").Replace("\n"," ");
        }
        public static void WriteIni(string destination, Dictionary<string,object> report) {
            string path=ReportPath(destination,true);
            StringBuilder ini=new StringBuilder("[PatchResult]"+Environment.NewLine+"tool="+Tool+Environment.NewLine);
            ini.Append("status="+(IniValue(report,"exit_code")=="0" ? "success" : "failed")+Environment.NewLine);
            foreach (string key in new string[] {"exit_code","language","game_dir","state","action","error"})
                ini.Append(key+"="+IniValue(report,key)+Environment.NewLine);
            ini.Append("changed="+(IniValue(report,"changed")=="True" ? "1" : "0")+Environment.NewLine);
            // Windows profile APIs transparently read this Unicode INI, including non-ASCII paths.
            File.WriteAllText(path,ini.ToString(),Encoding.Unicode);
        }
        public static Dictionary<string,object> PendingReport(string action,string gameDirectory) {
            Dictionary<string,object> report=Report(action);
            report["status"]="pending"; report["exit_code"]=14;
            report["game_dir"]=Path.GetFullPath(gameDirectory);
            return report;
        }
        public static string Serialize(Dictionary<string,object> report) { return Json.Serialize(report); }
    }
    public static class Program {
        [STAThread] public static int Main(string[] args) {
            string action=null,game=null,reportPath=null,iniPath=null;
            for (int i=0;i<args.Length;i++) {
                if (args[i]=="--apply" || args[i]=="--verify" || args[i]=="--rollback") {
                    if (action!=null) return 64; action=args[i].Substring(2);
                } else if ((args[i]=="--game-dir" || args[i]=="--report" || args[i]=="--result-ini") && i+1<args.Length) {
                    string option=args[i++];
                    if (option=="--game-dir") { if (game!=null) return 64; game=args[i]; }
                    else if (option=="--report") { if (reportPath!=null) return 64; reportPath=args[i]; }
                    else { if (iniPath!=null) return 64; iniPath=args[i]; }
                } else return 64;
            }
            if (action==null || String.IsNullOrWhiteSpace(game)) return 64;
            // Validate both report destinations and prove they are writable before touching the executable.
            // A stale report never survives a worker interruption as a false success.
            try {
                if (reportPath!=null) Backend.ReportPath(reportPath,false);
                if (iniPath!=null) Backend.ReportPath(iniPath,true);
                Dictionary<string,object> pending=Backend.PendingReport(action,game);
                if (reportPath!=null) Backend.WriteReport(reportPath,pending);
                if (iniPath!=null) Backend.WriteIni(iniPath,pending);
            } catch (PatchFailure failure) { return failure.Code; }
              catch (Exception) { return 14; }
            Dictionary<string,object> report; int result=Backend.Execute(action,game,out report);
            try {
                Console.WriteLine(Backend.Serialize(report));
                if (reportPath!=null) Backend.WriteReport(reportPath,report);
                if (iniPath!=null) Backend.WriteIni(iniPath,report);
            } catch (Exception) { return result==0 ? 14 : result; }
            return result;
        }
    }
}
