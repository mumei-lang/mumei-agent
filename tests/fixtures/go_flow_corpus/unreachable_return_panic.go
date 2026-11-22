package main

func unreachableAfterReturn() int {
	return 1
	value := 2 // want: unreachable; unused value
}

func unreachableAfterPanic() int {
	panic("stop")
	value := 3 // want: unreachable; unused value
}
