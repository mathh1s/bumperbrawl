// Bends the render clock for game feel: a hit-stop holds the picture for a few frames on a big
// hit near you, and slow motion stretches the knockout that ends a round. The interpolated
// world falls a little behind while time is bent and quietly catches up afterwards, so nothing
// is skipped and the server never notices.

const MAX_LAG = 1500;
const CATCH_UP = 0.8; // extra speed while catching up

export class TimeWarp {
  constructor() {
    this.lag = 0;
    this.stopUntil = 0;
    this.slowUntil = 0;
    this.slowScale = 1;
    this.scale = 1;
  }

  hitStop(now, ms) {
    this.stopUntil = Math.max(this.stopUntil, now + ms);
  }

  slowMo(now, ms, scale) {
    this.slowUntil = now + ms;
    this.slowScale = scale;
  }

  get slow() {
    return performance.now() < this.slowUntil;
  }

  // advances by one frame of rawMs real time; returns how far behind the render clock runs
  update(now, rawMs) {
    let scale = 1;
    if (now < this.stopUntil) scale = 0;
    else if (now < this.slowUntil) scale = this.slowScale;
    if (scale < 1) {
      this.lag = Math.min(MAX_LAG, this.lag + rawMs * (1 - scale));
    } else {
      this.lag = Math.max(0, this.lag - rawMs * CATCH_UP);
      if (this.lag > 0) scale = 1 + CATCH_UP;
    }
    this.scale = scale;
    return this.lag;
  }
}
