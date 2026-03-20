// Example: effect mismatch violation for self-healing demo.
// The atom declares [Log] but uses FileWrite.write which requires FileWrite.

atom write_log(msg: Nat)
    effects: [Log];
    requires: msg >= 0;
    ensures: result == msg;
    body: {
        perform FileWrite.write(msg);
        msg
    };
