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
} Workspace;

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

/* Open Watcom's NT DLL startup invokes LibMain. */
BOOL WINAPI LibMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)instance; (void)reason; (void)reserved;
    return TRUE;
}
