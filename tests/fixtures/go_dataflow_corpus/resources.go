package main

import "os"

func fileLeakedOnEarlyReturn(path string, c bool) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	if c {
		return nil // want: resource_leak f
	}
	return f.Close()
}

func fileClosedByDefer(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return nil
}

func useAfterClose(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	f.Close()
	_, err = f.Stat() // want: use_after_close f
	return err
}

func useBeforeClose(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	_, err = f.Stat()
	f.Close()
	return err
}
