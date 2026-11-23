package main

type T struct{ v int }

func derefNilPointer() int {
	var p *T
	return p.v // want: uninitialized_use p
}

func derefAssignedPointer() int {
	var p *T
	p = &T{}
	return p.v
}

func derefPointerAssignedOnOneBranch(c bool) int {
	var p *T
	if c {
		p = &T{}
	}
	return p.v // want: uninitialized_use p
}

func derefGuardedPointer(c bool) int {
	var p *T
	if c {
		p = &T{}
	}
	if p == nil {
		return 0
	}
	return p.v
}

func indexNilSlice() int {
	var s []int
	return s[0] // want: uninitialized_use s
}

func indexAppendedSlice() int {
	var s []int
	s = append(s, 1)
	return s[0]
}

func callNilFunc() int {
	var f func() int
	return f() // want: uninitialized_use f
}

func derefPointerAfterBackwardGoto(n int) int {
	var p *T
again:
	if p == nil {
		p = &T{}
		goto again
	}
	return p.v
}
