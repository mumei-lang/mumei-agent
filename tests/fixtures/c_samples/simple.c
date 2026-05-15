#include <assert.h>

int add(int a, int b) {
    return a + b;
}

unsigned int clamp_nonzero(unsigned int x) {
    assert(x > 0);
    return x;
}
