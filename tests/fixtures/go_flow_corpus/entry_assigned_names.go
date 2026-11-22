package main

var packageState *int

func readsEntryAssignedNames(input *int, writeGlobal bool) int {
	value := *input
	input = new(int)
	if writeGlobal {
		packageState = new(int)
	}
	_ = *packageState
	return value
}
