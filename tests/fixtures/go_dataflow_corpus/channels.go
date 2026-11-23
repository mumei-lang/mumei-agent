package main

func sendAfterClose() {
	ch := make(chan int, 1)
	close(ch)
	ch <- 1 // want: send_on_closed_channel ch
}

func sendBeforeClose() {
	ch := make(chan int, 1)
	ch <- 1
	close(ch)
}

func closeNilChannel() {
	var ch chan int
	close(ch) // want: close_nil_channel ch
}

func closeMadeChannel() {
	var ch chan int
	ch = make(chan int)
	close(ch)
}

func closeTwice() {
	ch := make(chan int)
	close(ch)
	close(ch) // want: send_on_closed_channel ch
}

func sendAfterConditionalClose(c bool) {
	ch := make(chan int, 1)
	if c {
		close(ch)
		return
	}
	ch <- 1
}

func closeInLoopBody(n int) {
	for i := 0; i < n; i++ {
		ch := make(chan int)
		close(ch)
	}
}

func sendOnChannelClosedInDefer() {
	ch := make(chan int, 1)
	defer close(ch)
	ch <- 1
}
