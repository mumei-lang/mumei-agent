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
declare const dyn: any;
dyn.foo;
class Guard { watch(): void {} }
class Other { other(): void {} }
declare const maybe: Guard | undefined;
if (maybe !== undefined) { maybe.watch(); }
if (maybe) { maybe.watch(); }
maybe?.watch();
declare const either: Guard | Other;
if (either instanceof Guard) { either.watch(); } else { either.other(); }
either instanceof Guard ? either.watch() : either.other();
while (maybe !== undefined) { maybe.watch(); break; }
interface Da { kind: "a"; pa(): void }
interface Db { kind: "b"; pb(): void }
declare const du: Da | Db;
switch (du.kind) {
    case "a": du.pa(); break;
    default: du.pb();
}
const holder = { item: maybe };
holder.item;
