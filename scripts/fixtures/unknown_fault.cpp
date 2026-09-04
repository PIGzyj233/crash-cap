#include <windows.h>

extern "C" __declspec(dllexport) __declspec(noinline) void unknown_module_fault() {
  volatile const int* address = nullptr;
  volatile int value = *address;
  (void)value;
}
