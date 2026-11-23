struct V;

struct P {
    value: V,
}

impl P {
    fn new(value: V) -> P {
        P { value: value }
    }

    fn pm(&self) -> &P {
        self
    }
}

struct W {
    inner: P,
}

impl W {
    fn field(&self) -> &P {
        &self.inner
    }

    fn read(&self) -> &P {
        self.inner.pm()
    }
}

fn main() {
    let w = W {
        inner: P::new(V),
    };
    let _direct = w.inner.pm();
    let _through = w.field().pm();
    let _read = w.read();
    let p = P::new(V);
    let _copied = &p.value;
}
