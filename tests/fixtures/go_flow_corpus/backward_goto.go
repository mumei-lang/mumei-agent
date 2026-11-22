package main

func backwardGotoLoop() int {
	var value *int
again:
	if value == nil { // want: unassigned value
		value = new(int)
		goto again
	}
	return *value
}
