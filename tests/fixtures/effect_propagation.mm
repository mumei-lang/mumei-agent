// Fixture: effect propagation violation.
// main_handler declares [Log] but calls write_log which requires [Log, FileWrite].
// The missing FileWrite effect is not propagated.

atom write_log(msg: i64) -> i64
    effects: [Log, FileWrite];
    requires: msg >= 0;
    ensures: result == msg;
    body: {
        perform FileWrite.write(msg);
        msg
    };

atom main_handler(msg: i64) -> i64
    effects: [Log];
    requires: msg >= 0;
    ensures: result == msg;
    body: write_log(msg);
