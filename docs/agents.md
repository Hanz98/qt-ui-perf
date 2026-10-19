# Agent setup and the locked-session problem

What happens to a GUI test when nobody is logged in, or the screen is locked, differs a lot
between the two platforms. This page records the facts the plan relies on and the setup for
each lane. Commands are starting points; verify each on the real agent before relying on it.

## What a locked / absent session actually breaks

| Situation | Windows | Linux (X11 / Wayland desktop) |
|---|---|---|
| Agent runs as a service | Session 0: isolated, no interactive desktop, no DWM composition. Windows can be created but are never shown; `SendInput`, UI Automation and screenshots fail. Qt `offscreen` works; Qt `windows` plugin runs but un-composited. | systemd system service: no `DISPLAY`/`WAYLAND_DISPLAY`. Qt `offscreen` works. For a display you start your own (Xvfb/Xorg/Weston/eglfs). |
| Interactive session, screen **locked** | The secure desktop is active. Apps on the default desktop keep running, but DWM stops presenting them (`DXGI_STATUS_OCCLUDED`, Present may block or throttle), input injection lands on the lock screen, screenshots are black. Frame timings are meaningless. | X server keeps running, the app keeps rendering into its window, but the locker holds the input grab and most compositors throttle/unredirect occluded windows. Timings are unreliable; input injection (xdotool) fails. |
| RDP session disconnected | Session keeps running but the display adapter becomes the RDP virtual adapter, resolution may change, GPU acceleration is gone. | n/a |

Conclusion: the only configurations worth measuring in are
(a) a display we create and own (headless lane, or Xvfb/Xorg/eglfs we start), and
(b) a dedicated, auto-logged-on, never-locked console session (Windows display lane).

## Lane: headless (both OSes)

Environment set by `tools/perfdrive.py`:

```
QT_QPA_PLATFORM=offscreen
QT_QPA_OFFSCREEN_NO_GLX=0            # Qt 6 offscreen can still do OpenGL via GLX/EGL on Linux
QSG_RHI_PREFER_SOFTWARE_RENDERER=1   # Qt 6 Quick: WARP on Windows, llvmpipe on Linux
QT_QUICK_BACKEND=software            # alternative: Quick 2D renderer, no GL at all (deterministic, fewer features)
LIBGL_ALWAYS_SOFTWARE=1              # Linux: force Mesa llvmpipe even if a GPU is present
QT_SCALE_FACTOR=1                    # pin DPI so layout is identical everywhere
QT_LOGGING_RULES=qt.scenegraph.time.*=true   # Quick only, per-frame sync/render times on stderr
```

Qt 5 note: `offscreen` has no OpenGL on Windows in Qt 5; use `QT_QUICK_BACKEND=software`, or
`QT_OPENGL=software` (Mesa `opengl32sw.dll` shipped with Qt) with the `windows` plugin —
which does run in Session 0, just invisible.

Runs in: Windows service agents (Session 0), Linux systemd agents, Docker containers,
locked sessions, anywhere. This lane gates merges.

## Lane: display, Linux

Choose one, in order of fidelity:

1. **Xvfb + llvmpipe** (any machine, no GPU, no compositor). Deterministic, CPU-bound.
   ```sh
   xvfb-run -a -s "-screen 0 1920x1080x24 +extension GLX" python tools/perfdrive.py ...
   ```
   Package: `xorg-server-xvfb` (Arch), `xvfb` (Debian/Ubuntu).
2. **Bare Xorg on a free VT** on a dedicated GPU box, no display manager, no desktop
   session. The Jenkins agent service starts it (or a systemd unit `xorg-perf.service`
   does, with `Xorg :1 vt7 -nolisten tcp` and `-config` using the real driver or
   `xf86-video-dummy` when there is no monitor). Export `DISPLAY=:1`. Optionally run a
   minimal compositor (`picom`, or none) so vsync behaviour matches the target desktop.
3. **`QT_QPA_PLATFORM=eglfs`** directly on KMS/DRM. No X, no Wayland, no compositor;
   the app owns the screen. Needs the agent user in the `video`/`render` groups and no
   other DRM master (so no desktop session on that GPU). Quietest numbers; least like a
   user's desktop.
4. **Headless Weston** for Wayland-specific behaviour:
   `weston --backend=headless-backend.so --width=1920 --height=1080` and
   `QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY=wayland-1`.

Agent service (`ci/linux-agent-setup.sh` will script this):
- `systemd` system unit for the Jenkins agent, `User=jenkins`, no graphical session.
- CPU governor `performance`; optionally `echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo`.
- `perf` installed and `kernel.perf_event_paranoid <= 1` so QtTest `-perfcounter` works.

## Lane: display, Windows

Only on a dedicated machine labelled `perf-display-windows`. Setup
(`ci/windows-agent-setup.ps1` will script what can be scripted):

1. Create a local test user; **auto-logon** it (Sysinternals `Autologon.exe`, or the
   `Winlogon` registry keys `AutoAdminLogon`, `DefaultUserName`, `DefaultPassword`).
2. **Do not install the agent as a service.** Create a Scheduled Task, trigger
   *At log on of* that user, action `java -jar agent.jar -url … -secret …` (or
   `jenkins-agent.exe`), "Run only when user is logged on", highest privileges, restart on
   failure. The agent then lives in the interactive console session with a real desktop.
3. Disable lock and screensaver: policy `InactivityTimeoutSecs=0`, `ScreenSaveActive=0`,
   `Power: Turn off display = Never`, `Require sign-in on wakeup = Never`; disable sleep.
4. Give it a display: a real monitor or an **HDMI dummy plug** on a physical box; on a VM
   a virtual display adapter (e.g. the hypervisor's, or an IDD driver). Without any
   display DWM may suspend presentation.
5. House rule: **never RDP into it** for maintenance during work hours. If someone must,
   they leave with `tscon <sessionId> /dest:console` (from an elevated prompt inside the
   RDP session) instead of closing the window, which hands the session back to the console
   unlocked. Closing the RDP window leaves the console locked until the next reboot.
6. Pin resolution 1920×1080 @ 100 % scaling, high-performance power plan, GPU driver
   version recorded in the result JSON.

Sanity checks the pipeline runs before measuring on this lane and fails fast on:
- `(Get-Process -Id $PID).SessionId -ne 0` (we are not in Session 0),
- `query user` shows the test user `Active` on `console`,
- a small Qt probe window is reported visible and `GetForegroundWindow` is not the lock
  screen (`LogonUI.exe`).

## What each lane may conclude

| Metric | headless | display |
|---|---|---|
| startup to first frame | yes (CPU part) | yes |
| click → painted | yes | yes |
| main-thread jank / event latency | yes | yes |
| QML instantiation, model/layout cost | yes (best, use `-perfcounter instructions`) | noisy |
| fps, frame pacing, dropped frames | relative only (software renderer) | yes |
| GPU-bound effects, shaders | no | yes |
| memory | yes | yes |
