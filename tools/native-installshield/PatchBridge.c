/* Native x86 stdcall adapter for the original InstallShield 5 script engine.
 * No game/UI/audio execution. This DLL synchronously waits for the managed
 * windowless worker and returns its actual exit code to the script caller.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define LIMIT 4096
#define BACKEND_NAME L"Cabela4x4PatchBackend.exe"

typedef struct Workspace {
    wchar_t selected[LIMIT], source[LIMIT], reports[LIMIT];
    wchar_t worker[LIMIT], json[LIMIT], ini[LIMIT], command[LIMIT];
    wchar_t converted[LIMIT], result[32];
    wchar_t module[LIMIT], logfile[LIMIT];
    char sourceAnsi[LIMIT], reportsAnsi[LIMIT], message[240];
} Workspace;

static HINSTANCE bridge_instance;
static LONG receipt_serial;

static int convert_directory(const char *input, wchar_t *output, wchar_t *converted)
{
    DWORD length;
    int i;
    if (!input || !input[0]) return 64;
    if (!MultiByteToWideChar(CP_ACP, 0, input, -1, converted, LIMIT)) return 64;
    for (i = 0; converted[i]; ++i)
        if (converted[i] == L'"' || converted[i] == L'\r' || converted[i] == L'\n') return 64;
    length = GetFullPathNameW(converted, LIMIT, output, NULL);
    if (!length || length >= LIMIT) return 13;
    while (length > 3 && (output[length-1] == L'\\' || output[length-1] == L'/'))
        output[--length] = 0;
    return 0;
}

static int append(wchar_t *output, const wchar_t *text)
{
    if (lstrlenW(output) + lstrlenW(text) >= LIMIT) return 64;
    lstrcatW(output, text);
    return 0;
}

static int child_path(wchar_t *output, const wchar_t *directory, const wchar_t *name)
{
    output[0] = 0;
    if (append(output, directory)) return 64;
    if (output[lstrlenW(output)-1] != L'\\' && append(output, L"\\")) return 64;
    return append(output, name);
}

/* Quote according to the Windows CommandLineToArgv/CRT rules. A trailing
 * backslash must be doubled before the closing quote, including C:\ roots.
 */
static int argument(wchar_t *command, const wchar_t *value)
{
    int slashes = 0;
    const wchar_t *cursor;
    if (append(command, L"\"")) return 64;
    for (cursor = value; *cursor; ++cursor) {
        wchar_t one[2]; one[0] = *cursor; one[1] = 0;
        if (*cursor == L'\\') { ++slashes; continue; }
        while (slashes > 0) { if (append(command,L"\\")) return 64; --slashes; }
        if (append(command,one)) return 64;
    }
    while (slashes > 0) { if (append(command,L"\\\\")) return 64; --slashes; }
    return append(command,L"\"");
}

static int apply_bridge(const char *selectedDir, const char *sourceDir, const char *reportDir, Workspace *workspace)
{
    wchar_t *selected=workspace->selected, *source=workspace->source, *reports=workspace->reports;
    wchar_t *worker=workspace->worker, *json=workspace->json, *ini=workspace->ini;
    wchar_t *command=workspace->command, *result=workspace->result;
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    DWORD attributes, wait, code;
    int error;
    error = convert_directory(selectedDir, selected, workspace->converted); if (error) return error;
    error = convert_directory(sourceDir, source, workspace->converted); if (error) return error;
    error = convert_directory(reportDir, reports, workspace->converted); if (error) return error;
    attributes = GetFileAttributesW(reports);
    if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY) || (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) return 13;
    if (child_path(worker,source,BACKEND_NAME) || child_path(json,reports,L"patch-result.json") || child_path(ini,reports,L"patch-result.ini")) return 64;
    attributes = GetFileAttributesW(worker);
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) return 14;
    command[0] = 0;
    if (argument(command,worker) || append(command,L" --apply --game-dir ") || argument(command,selected) || append(command,L" --report ") || argument(command,json) || append(command,L" --result-ini ") || argument(command,ini)) return 64;
    ZeroMemory(&startup,sizeof(startup)); ZeroMemory(&process,sizeof(process));
    startup.cb=sizeof(startup); startup.dwFlags=STARTF_USESHOWWINDOW; startup.wShowWindow=SW_HIDE;
    if (!CreateProcessW(worker,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,source,&startup,&process)) return 14;
    CloseHandle(process.hThread);
    wait=WaitForSingleObject(process.hProcess,INFINITE);
    if (wait!=WAIT_OBJECT_0 || !GetExitCodeProcess(process.hProcess,&code)) { CloseHandle(process.hProcess); return 14; }
    CloseHandle(process.hProcess);
    if (code) return code <= 255 ? (int)code : 14;
    /* A worker success also needs a completed receipt; never trust a stale
     * report alone, since the real process exit is always checked above. */
    GetPrivateProfileStringW(L"PatchResult",L"status",L"missing",result,32,ini);
    if (lstrcmpW(result,L"success")!=0) return 14;
    GetPrivateProfileStringW(L"PatchResult",L"exit_code",L"missing",result,32,ini);
    return lstrcmpW(result,L"0")==0 ? 0 : 14;
}

int WINAPI PatchGame(const char *selectedDir, const char *sourceDir, const char *reportDir)
{
    Workspace *workspace;
    int result;
    /* InstallShield controls the caller's thread stack. Keep path buffers on
     * the heap so the DLL never assumes a large committed host stack. */
    workspace=(Workspace *)HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(Workspace));
    if (!workspace) return 14;
    result=apply_bridge(selectedDir,sourceDir,reportDir,workspace);
    HeapFree(GetProcessHeap(),0,workspace);
    return result;
}

static int to_ansi(const wchar_t *input, char *output)
{
    BOOL substituted=FALSE;
    UINT page=GetACP();
    if (!WideCharToMultiByte(page,0,input,-1,output,LIMIT,NULL,
                            page==CP_UTF8 ? NULL : &substituted)) return 13;
    return substituted ? 13 : 0;
}

static int own_directories(Workspace *workspace)
{
    DWORD count, attributes;
    int i, last=-1;
    FILETIME now;
    char suffix[96];
    wchar_t wide_suffix[96];
    count=GetModuleFileNameW(bridge_instance,workspace->module,LIMIT);
    if (!bridge_instance || !count || count>=LIMIT) return 14;
    for (i=0; workspace->module[i]; ++i)
        if (workspace->module[i]==L'\\' || workspace->module[i]==L'/') last=i;
    if (last<0) return 14;
    lstrcpyW(workspace->source,workspace->module);
    workspace->source[last==2 && workspace->source[1]==L':' ? 3 : last]=0;
    if (to_ansi(workspace->source,workspace->sourceAnsi)) return 13;
    count=GetTempPathW(LIMIT,workspace->reports);
    if (!count || count>=LIMIT) return 13;
    attributes=GetFileAttributesW(workspace->reports);
    if (attributes==INVALID_FILE_ATTRIBUTES || !(attributes&FILE_ATTRIBUTE_DIRECTORY)
        || (attributes&FILE_ATTRIBUTE_REPARSE_POINT)) return 13;
    GetSystemTimeAsFileTime(&now);
    wsprintfA(suffix,"c4x4-is-%08lx-%08lx%08lx-%08lx",
              GetCurrentProcessId(),now.dwHighDateTime,now.dwLowDateTime,
              (DWORD)InterlockedIncrement(&receipt_serial));
    if (!MultiByteToWideChar(CP_ACP,0,suffix,-1,wide_suffix,96)) return 13;
    if (append(workspace->reports,wide_suffix)) return 13;
    /* CreateDirectory is the ownership boundary: never reuse or overwrite a
     * colliding directory, even if it appears empty or contains old receipts. */
    if (!CreateDirectoryW(workspace->reports,NULL)) return 13;
    return to_ansi(workspace->reports,workspace->reportsAnsi);
}

/* A diagnostic breadcrumb is optional; the worker's fresh Temp receipts and
 * actual process exit remain the authority. Preserve unrelated stage files. */
static void installer_log(Workspace *workspace, const char *selected, int status)
{
    wchar_t stamp[64], number[32];
    HANDLE file;
    DWORD wrote, attributes;
    WORD bom=0xfeff;
    if (child_path(workspace->logfile,workspace->source,L"patch-installer.ini")) return;
    attributes=GetFileAttributesW(workspace->logfile);
    if (attributes!=INVALID_FILE_ATTRIBUTES) {
        if (attributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT)) return;
        GetPrivateProfileStringW(L"PatchInstaller",L"tool",L"",stamp,64,workspace->logfile);
        if (lstrcmpW(stamp,L"Cabela4x4PatchBridge")) return;
    } else {
        file=CreateFileW(workspace->logfile,GENERIC_WRITE,0,NULL,CREATE_NEW,
                         FILE_ATTRIBUTE_NORMAL,NULL);
        if (file==INVALID_HANDLE_VALUE) return;
        if (!WriteFile(file,&bom,sizeof(bom),&wrote,NULL) || wrote!=sizeof(bom)) {
            CloseHandle(file); return;
        }
        CloseHandle(file);
    }
    wsprintfW(number,L"%d",status);
    WritePrivateProfileStringW(L"PatchInstaller",L"tool",L"Cabela4x4PatchBridge",workspace->logfile);
    WritePrivateProfileStringW(L"PatchInstaller",L"module",workspace->module,workspace->logfile);
    WritePrivateProfileStringW(L"PatchInstaller",L"report_dir",workspace->reports,workspace->logfile);
    if (selected && MultiByteToWideChar(CP_ACP,0,selected,-1,workspace->converted,LIMIT))
        WritePrivateProfileStringW(L"PatchInstaller",L"game_dir",workspace->converted,workspace->logfile);
    WritePrivateProfileStringW(L"PatchInstaller",L"exit_code",number,workspace->logfile);
    WritePrivateProfileStringW(L"PatchInstaller",L"status",status==0 ? L"success" : L"failed",workspace->logfile);
}

static const char *installer_error(int status)
{
    switch (status) {
    case 10: return "The selected executable is not a supported version 1.2 build.";
    case 11: return "Close the game and its launcher, then try again.";
    case 12: return "The original backup is missing or changed. Check the backup before retrying.";
    case 13: return "The selected folder or the temporary receipt folder could not be used.";
    case 14: return "The patch worker could not complete. Check the installer files and receipt.";
    case 15: return "Executable verification failed. No successful installation was recorded.";
    case 64: return "Select a valid game folder containing 4x4 Adventure.exe.";
    default: return "The patch worker returned an error. Check the temporary patch receipt.";
    }
}

/* InstallShield's supported CallDLLFx ABI. The script supplies a dedicated
 * writable STRING copy with at least258 bytes; TARGETDIR is never overwritten.
 * On failure only this copy receives a short, ASCII English error message. */
LONG WINAPI PatchInstaller(HWND owner, LONG *status, LPSTR folder_and_error)
{
    Workspace *workspace;
    int code;
    (void)owner;
    if (status) *status=14;
    if (!status || !folder_and_error) { if (status) *status=64; return 64; }
    workspace=(Workspace *)HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(Workspace));
    if (!workspace) {
        *status=14;
        lstrcpynA(folder_and_error,installer_error(14),240);
        return 14;
    }
    code=own_directories(workspace);
    if (!code) code=apply_bridge(folder_and_error,workspace->sourceAnsi,
                                workspace->reportsAnsi,workspace);
    if (workspace->source[0]) installer_log(workspace,folder_and_error,code);
    *status=code;
    if (code) lstrcpynA(folder_and_error,installer_error(code),240);
    HeapFree(GetProcessHeap(),0,workspace);
    return code;
}

/* Open Watcom's NT DLL startup invokes LibMain. */
BOOL WINAPI LibMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason==DLL_PROCESS_ATTACH) bridge_instance=instance;
    return TRUE;
}
