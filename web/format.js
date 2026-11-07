const PAD = 2;

export function ageText(seconds) {
  if (seconds === null || seconds === undefined) return "no reading";
  const whole = Math.round(seconds);
  if (whole < 90) return `${whole} s ago`;
  if (whole < 5400) return `${Math.round(whole / 60)} min ago`;
  if (whole < 172800) return `${Math.round(whole / 3600)} h ago`;
  return `${Math.round(whole / 86400)} days ago`;
}

export function clock(date) {
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(PAD, "0"))
    .join(":");
}

export function temperature(value) {
  return value === null || value === undefined ? "–" : value.toFixed(1);
}
