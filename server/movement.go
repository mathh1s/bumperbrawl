package main

import "math"

// Movement tuning. The client runs the same rules to predict its own blob,
// so these go out in the welcome message and web/predict.js must match move().
const (
	runSpeed   = 10.0 // top speed from the stick alone
	runAccel   = 62.0 // how quickly the stick gets you to top speed or turns you around
	brakeAccel = 46.0 // how quickly you stop after letting go
	airAccel   = 30.0 // steering while jumping
	looseAccel = 12.0 // steering while flying from a hit or a dash
	drag       = 3.2  // how fast speed above runSpeed bleeds off
	stunBase   = 0.12 // seconds of loose control after any shove
	stunPerVel = 0.03 // plus this much per unit of velocity the shove added
	stunMax    = 0.6
)

func movementConfig() map[string]float64 {
	return map[string]float64{
		"runSpeed": runSpeed, "runAccel": runAccel, "brakeAccel": brakeAccel, "airAccel": airAccel,
		"looseAccel": looseAccel, "drag": drag, "dashImpulse": dashImpulse, "dashCooldown": dashCooldown,
		"dashTime": dashTime, "chargeMax": chargeMax, "chargeSlow": chargeSlow, "heavySlow": heavySlow,
		"jumpSpeed": jumpSpeed, "jumpGravity": jumpGravity, "jumpCooldown": jumpCooldown,
	}
}

// shove adds velocity from outside (bumps, slams, the log) and takes away control for a moment,
// so a hit carries you instead of being cancelled by the stick
func (p *Player) shove(vx, vz float64) {
	p.VX += vx
	p.VZ += vz
	p.Stun = math.Max(p.Stun, math.Min(stunMax, stunBase+stunPerVel*math.Hypot(vx, vz)))
}

// move steers a blob from its input, fires a pending dash and integrates its position.
// Below top speed the stick is in charge, so starting, turning and stopping are quick;
// above it (after a hit or a dash) speed bleeds off with drag and the stick only nudges.
func (p *Player) move(dt float64) {
	p.Stun = math.Max(0, p.Stun-dt)

	inLen := math.Hypot(p.InX, p.InZ)
	if inLen > 0.1 {
		p.Angle = math.Atan2(p.InX, p.InZ)
	}
	top := runSpeed
	if p.Pow == powHeavy {
		top *= heavySlow
	}
	if p.Charging {
		p.ChargeT = math.Min(chargeMax, p.ChargeT+dt)
		top *= chargeSlow
	}

	speed := math.Hypot(p.VX, p.VZ)
	if p.Stun > 0 || p.DashT > 0 || speed > top+0.01 {
		p.VX += p.InX * looseAccel * dt
		p.VZ += p.InZ * looseAccel * dt
		damp := 1 - drag*dt
		p.VX *= damp
		p.VZ *= damp
	} else {
		acc := runAccel
		switch {
		case p.Airborne:
			acc = airAccel
		case inLen < 0.1:
			acc = brakeAccel
		}
		dx, dz := p.InX*top-p.VX, p.InZ*top-p.VZ
		if d := math.Hypot(dx, dz); d > acc*dt {
			dx, dz = dx/d*acc*dt, dz/d*acc*dt
		}
		p.VX += dx
		p.VZ += dz
	}

	if p.WantDash && p.DashCD == 0 {
		// a tap is a plain dash; holding trades mobility for a longer, heavier launch
		pow := 0.0
		if p.Charging {
			pow = p.ChargeT / chargeMax
		}
		imp := dashImpulse * (1 + 0.9*pow)
		p.VX += math.Sin(p.Angle) * imp
		p.VZ += math.Cos(p.Angle) * imp
		p.DashCD = dashCooldown + 0.6*pow
		p.DashCDMax = p.DashCD
		p.DashT = dashTime * (1 + 0.6*pow)
		p.DashPow = pow
		p.Charging, p.ChargeT = false, 0
		p.Ghost = 0
		p.Stats.Dashes++
	}
	p.WantDash = false

	p.X += p.VX * dt
	p.Z += p.VZ * dt
}
