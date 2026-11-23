package main

func writeNilMap() {
	var m map[string]int
	m["a"] = 1 // want: nil_map_write m
}

func writeMadeMap() {
	m := make(map[string]int)
	m["a"] = 1
}

func writeLiteralMap() {
	m := map[string]int{}
	m["a"] = 1
}

func writeMapAfterBranchInit(c bool) {
	var m map[string]int
	if c {
		m = make(map[string]int)
	} else {
		m = map[string]int{}
	}
	m["a"] = 1
}

func writeMapInitializedOnOneBranch(c bool) {
	var m map[string]int
	if c {
		m = make(map[string]int)
	}
	m["a"] = 1 // want: nil_map_write m
}

func writeMapAfterNilGuard(m map[string]int) {
	if m == nil {
		m = make(map[string]int)
	}
	m["a"] = 1
}

func writeMapInitializedInSwitch(k int) {
	var m map[string]int
	switch k {
	case 0:
		m = make(map[string]int)
	default:
		m = map[string]int{}
	}
	m["a"] = 1
}
