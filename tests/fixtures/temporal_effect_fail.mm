// Fixture: temporal effect violation.
// Attempts to write to a file handle after it has been closed.

atom bad_file_usage(path: Str) -> i64
    effects: [FileRead, FileWrite];
    body: {
        let h = perform FileRead.open(path);
        perform FileWrite.close(h);
        perform FileWrite.write(h, "data");
        0
    };
