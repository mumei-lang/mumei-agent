function choose(value: string): string;
function choose(value: number): number;
function choose(value: string | number): string | number {
  return value;
}
const selected = choose(1);
