class Counter {
  read(value: number) {
    const capture = () => value;
    return capture();
  }
}
