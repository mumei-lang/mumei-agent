package main

func afterUnconditionalBreak() {
	for {
		break
		value := 1 // want: unreachable; unused value
	}
}

func afterUnconditionalContinue() {
	for {
		continue
		value := 1 // want: unreachable; unused value
	}
}
