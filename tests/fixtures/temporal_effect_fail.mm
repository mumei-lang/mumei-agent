// Fixture: temporal effect violation.
// Temporal checks apply only to stateful effects (states/transition);
// write is attempted after the handle has been closed.

effect File
    states: [Closed, Open];
    initial: Closed;
    transition open: Closed -> Open;
    transition write: Open -> Open;
    transition close: Open -> Closed;

atom bad_file_usage() -> i64
    effects: [File];
    body: {
        perform File.open();
        perform File.close();
        perform File.write();
        0
    };
