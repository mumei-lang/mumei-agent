interface Shape { area(): number }
class Engine { start(): void {} }
class Car implements Shape {
    engine: Engine = new Engine();
    base(): void {}
    area(): number { return 0 }
    run(other: Car): void {
        this.engine.start();
        other.engine.start();
        this.base();
        other.area();
    }
}
namespace N {
    export function help(): void {}
    export class Inner { ping(): void {} }
}
enum Direction { Up, Down }
const heading = Direction.Up;
N.help();
const inner = new N.Inner();
inner.ping();
const s: Shape = new Car();
s.area();
const cars: Car[] = [new Car()];
cars[0].base();
cars.push(new Car());
cars.length;
class Quoted { "m"(): void {} }
const quoted = new Quoted(); quoted.m();
declare const record: Record<"undefined", number>;
record.undefined;
Car.prototype;
