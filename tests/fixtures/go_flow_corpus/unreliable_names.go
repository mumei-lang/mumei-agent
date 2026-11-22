package main

func closureAssignedName(condition bool) int {
	var state *int
	writer := func() { state = new(int) }
	if condition {
		writer()
	}
	// The closure writes only on the true branch; the false path leaves state nil.
	return *state // want: unassigned state
}

func addressTakenName(condition bool) int {
	var state *int
	pointer := &state
	if condition {
		*pointer = new(int)
	}
	// Taking the address is not a value read; the false path leaves state nil.
	return *state // want: unassigned state
}
