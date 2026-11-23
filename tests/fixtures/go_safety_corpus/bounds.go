package main

func Index(s []int, i int) int {
	return s[i] // want: index_out_of_bounds s[i]
}

func IndexFirst(s []int) int {
	return s[0] // want: index_out_of_bounds s[0]
}

func IndexFirstAfterLenGuard(s []int) int {
	if len(s) == 0 {
		return 0
	}
	return s[0]
}

func IndexGuarded(s []int, i int) int {
	if i < 0 || i >= len(s) {
		return 0
	}
	return s[i]
}

func IndexGuardedUpperOnly(s []int, i int) int {
	if i >= len(s) {
		return 0
	}
	return s[i] // want: index_out_of_bounds s[i]
}

func IndexInForLoop(s []int) int {
	for i := 0; i < len(s); i++ {
		if s[i] > 0 {
			return s[i]
		}
	}
	return 0
}

func IndexInRange(s []int) int {
	for i := range s {
		return s[i]
	}
	return 0
}

func IndexLast(s []int) int {
	return s[len(s)-1] // want: index_out_of_bounds s[len(s)-1]
}

func IndexLastAfterGuard(s []int) int {
	if len(s) == 0 {
		return 0
	}
	return s[len(s)-1]
}

func IndexFixedArray(a [4]int) int {
	return a[3]
}

func IndexLoopOffByOne(s []int) int {
	for i := 0; i <= len(s); i++ {
		if i == len(s) {
			return s[i] // want: index_out_of_bounds s[i]
		}
	}
	return 0
}

func IndexMap(m map[string]int, k string) int {
	return m[k]
}
