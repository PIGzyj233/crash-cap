#include "capture_protocol.h"

#include <windows.h>
#include <dbghelp.h>

#include <fstream>
#include <string>
#include <vector>

#pragma comment(lib, "Dbghelp.lib")

namespace {

struct Options {
  std::wstring target;
  std::wstring dump;
  std::wstring context;
  std::wstring result;
  std::wstring ready_event;
  std::wstring release_event;
  bool no_exception = false;
  bool terminate_after_dump = false;
};

bool take_value(int argc, wchar_t** argv, const wchar_t* name,
                std::wstring* value) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::wstring(argv[i]) == name) {
      *value = argv[i + 1];
      return true;
    }
  }
  return false;
}

bool has_flag(int argc, wchar_t** argv, const wchar_t* name) {
  for (int i = 1; i < argc; ++i) {
    if (std::wstring(argv[i]) == name) {
      return true;
    }
  }
  return false;
}

bool parse_options(int argc, wchar_t** argv, Options* options) {
  options->no_exception = has_flag(argc, argv, L"--no-exception");
  options->terminate_after_dump =
      has_flag(argc, argv, L"--terminate-after-dump");
  return take_value(argc, argv, L"--target", &options->target) &&
         take_value(argc, argv, L"--dump", &options->dump) &&
         take_value(argc, argv, L"--context", &options->context) &&
         take_value(argc, argv, L"--result", &options->result) &&
         take_value(argc, argv, L"--ready-event", &options->ready_event) &&
         take_value(argc, argv, L"--release-event", &options->release_event);
}

std::wstring quote_argument(const std::wstring& value) {
  std::wstring quoted = L"\"";
  for (const wchar_t character : value) {
    if (character == L'"') {
      quoted += L"\\\"";
    } else {
      quoted += character;
    }
  }
  quoted += L"\"";
  return quoted;
}

bool write_result(const std::wstring& path, const Options& options,
                  bool dump_ok, DWORD dump_error, bool target_wait_ok,
                  DWORD target_wait_error, DWORD target_exit_code) {
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  if (!output) {
    return false;
  }
  output << "{\n"
         << "  \"collector\": \"MiniDumpWriteDump\",\n"
         << "  \"no_exception\": "
         << (options.no_exception ? "true" : "false") << ",\n"
         << "  \"terminate_after_dump\": "
         << (options.terminate_after_dump ? "true" : "false") << ",\n"
         << "  \"dump_ok\": " << (dump_ok ? "true" : "false") << ",\n"
         << "  \"dump_error\": " << dump_error << ",\n"
         << "  \"target_wait_ok\": "
         << (target_wait_ok ? "true" : "false") << ",\n"
         << "  \"target_wait_error\": " << target_wait_error << ",\n"
         << "  \"target_exit_code\": " << target_exit_code << "\n"
         << "}\n";
  return output.good();
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  Options options;
  if (!parse_options(argc, argv, &options)) {
    return 2;
  }

  HANDLE ready_event = CreateEventW(nullptr, TRUE, FALSE,
                                    options.ready_event.c_str());
  HANDLE release_event = CreateEventW(nullptr, TRUE, FALSE,
                                      options.release_event.c_str());
  if (ready_event == nullptr || release_event == nullptr) {
    return 3;
  }

  std::wstring scenario;
  if (!take_value(argc, argv, L"--scenario", &scenario)) {
    CloseHandle(ready_event);
    CloseHandle(release_event);
    return 4;
  }
  std::wstring command_line = quote_argument(options.target) +
                              L" --scenario " + quote_argument(scenario) +
                              L" --context " + quote_argument(options.context) +
                              L" --ready-event " +
                              quote_argument(options.ready_event) +
                              L" --release-event " +
                              quote_argument(options.release_event);
  std::vector<wchar_t> mutable_command_line(command_line.begin(),
                                             command_line.end());
  mutable_command_line.push_back(L'\0');

  STARTUPINFOW startup_info{};
  startup_info.cb = sizeof(startup_info);
  PROCESS_INFORMATION process_info{};
  const BOOL created = CreateProcessW(
      nullptr, mutable_command_line.data(), nullptr, nullptr, FALSE,
      CREATE_NO_WINDOW, nullptr, nullptr, &startup_info, &process_info);
  if (!created) {
    const DWORD error = GetLastError();
    write_result(options.result, options, false, error, false, error, 0);
    CloseHandle(ready_event);
    CloseHandle(release_event);
    return 5;
  }
  CloseHandle(process_info.hThread);

  const DWORD ready_wait = WaitForSingleObject(ready_event, 30000);
  if (ready_wait != WAIT_OBJECT_0) {
    const DWORD error = ready_wait == WAIT_FAILED ? GetLastError()
                                                   : ERROR_TIMEOUT;
    SetEvent(release_event);
    TerminateProcess(process_info.hProcess, error);
    WaitForSingleObject(process_info.hProcess, 5000);
    write_result(options.result, options, false, error, false, error, 0);
    CloseHandle(process_info.hProcess);
    CloseHandle(ready_event);
    CloseHandle(release_event);
    return 6;
  }

  HANDLE dump_file = CreateFileW(options.dump.c_str(), GENERIC_WRITE, 0,
                                 nullptr, CREATE_ALWAYS,
                                 FILE_ATTRIBUTE_NORMAL, nullptr);
  if (dump_file == INVALID_HANDLE_VALUE) {
    const DWORD error = GetLastError();
    SetEvent(release_event);
    TerminateProcess(process_info.hProcess, error);
    WaitForSingleObject(process_info.hProcess, 5000);
    write_result(options.result, options, false, error, false, error, 0);
    CloseHandle(process_info.hProcess);
    CloseHandle(ready_event);
    CloseHandle(release_event);
    return 7;
  }

  MINIDUMP_EXCEPTION_INFORMATION exception_information{};
  MINIDUMP_EXCEPTION_INFORMATION* exception_pointer = nullptr;
  crashcap::ContextSnapshot snapshot;
  if (!options.no_exception) {
    std::ifstream input(options.context, std::ios::binary);
    input.read(reinterpret_cast<char*>(&snapshot), sizeof(snapshot));
    const bool snapshot_ok =
        input.gcount() == sizeof(snapshot) &&
        snapshot.magic == crashcap::kContextSnapshotMagic &&
        snapshot.version == crashcap::kContextSnapshotVersion;
    if (!snapshot_ok) {
      CloseHandle(dump_file);
      SetEvent(release_event);
      TerminateProcess(process_info.hProcess, ERROR_INVALID_DATA);
      WaitForSingleObject(process_info.hProcess, 5000);
      write_result(options.result, options, false, ERROR_INVALID_DATA, false,
                   ERROR_INVALID_DATA, 0);
      CloseHandle(process_info.hProcess);
      CloseHandle(ready_event);
      CloseHandle(release_event);
      return 8;
    }
    EXCEPTION_POINTERS exception_pointers{};
    exception_pointers.ExceptionRecord = &snapshot.exception_record;
    exception_pointers.ContextRecord = &snapshot.context;
    exception_information.ThreadId = snapshot.thread_id;
    exception_information.ExceptionPointers = &exception_pointers;
    exception_information.ClientPointers = FALSE;
    exception_pointer = &exception_information;
  }

  constexpr MINIDUMP_TYPE dump_type =
      static_cast<MINIDUMP_TYPE>(MiniDumpWithDataSegs |
                                 MiniDumpWithHandleData |
                                 MiniDumpWithUnloadedModules |
                                 MiniDumpWithProcessThreadData |
                                 MiniDumpWithThreadInfo |
                                 MiniDumpWithIndirectlyReferencedMemory);
  const BOOL dump_ok = MiniDumpWriteDump(
      process_info.hProcess, process_info.dwProcessId, dump_file, dump_type,
      exception_pointer, nullptr, nullptr);
  const DWORD dump_error = dump_ok ? ERROR_SUCCESS : GetLastError();
  CloseHandle(dump_file);

  SetEvent(release_event);
  if (options.terminate_after_dump) {
    TerminateProcess(process_info.hProcess, ERROR_SUCCESS);
  }
  const DWORD target_wait = WaitForSingleObject(process_info.hProcess, 30000);
  const bool target_wait_ok = target_wait == WAIT_OBJECT_0;
  DWORD target_wait_error = ERROR_SUCCESS;
  if (target_wait == WAIT_FAILED) {
    target_wait_error = GetLastError();
  } else if (!target_wait_ok) {
    target_wait_error = ERROR_TIMEOUT;
    TerminateProcess(process_info.hProcess, target_wait_error);
    WaitForSingleObject(process_info.hProcess, 5000);
  }
  DWORD target_exit_code = 0;
  GetExitCodeProcess(process_info.hProcess, &target_exit_code);
  const bool result_ok = write_result(
      options.result, options, dump_ok != FALSE, dump_error, target_wait_ok,
      target_wait_error, target_exit_code);
  CloseHandle(process_info.hProcess);
  CloseHandle(ready_event);
  CloseHandle(release_event);
  if (dump_ok == FALSE || !result_ok) {
    return 9;
  }
  return 0;
}
