package main

import "sync"

func lockHeldOnEarlyReturn(mu *sync.Mutex, c bool) int {
	mu.Lock()
	if c {
		return 1 // want: lock_held_at_return mu
	}
	mu.Unlock()
	return 0
}

func lockReleasedByDefer(mu *sync.Mutex, c bool) int {
	mu.Lock()
	defer mu.Unlock()
	if c {
		return 1
	}
	return 0
}

func lockReleasedOnEveryPath(mu *sync.Mutex, c bool) int {
	mu.Lock()
	if c {
		mu.Unlock()
		return 1
	}
	mu.Unlock()
	return 0
}

func doubleLock(mu *sync.Mutex) {
	mu.Lock()
	mu.Lock() // want: double_lock mu
	mu.Unlock()
}

// The caller may hold a parameter mutex, so this is not a definite defect.
func unlockParameterMutex(mu *sync.Mutex) {
	mu.Unlock()
}

func unlockAfterUnlock(mu *sync.Mutex) {
	mu.Lock()
	mu.Unlock()
	mu.Unlock() // want: unlock_of_unlocked mu
}

func lockUnlockInLoop(mu *sync.Mutex, n int) {
	for i := 0; i < n; i++ {
		mu.Lock()
		mu.Unlock()
	}
}

func lockAndUnlockUnderSameCondition(mu *sync.Mutex, c bool) {
	if c {
		mu.Lock()
	}
	if c {
		mu.Unlock()
	}
}

func lockRetriedThroughBackwardGoto(mu *sync.Mutex, n int) {
again:
	mu.Lock()
	if n > 0 {
		n--
		mu.Unlock()
		goto again
	}
	mu.Unlock()
}

func localMutexDoubleUnlock() {
	var mu sync.Mutex
	mu.Lock()
	mu.Unlock()
	mu.Unlock() // want: unlock_of_unlocked mu
}
