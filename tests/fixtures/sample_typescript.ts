/**
 * Add two account balances.
 * @requires a >= 0
 * @requires b >= 0
 * @ensures result == a + b
 */
export function addBalances(a: number, b: number): number {
  return a + b;
}

/**
 * Check whether a balance is usable.
 * @post result == (balance > 0)
 */
export const hasFunds = (balance: number): boolean => balance > 0;
