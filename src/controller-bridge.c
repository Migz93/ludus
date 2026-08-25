/* Map common gamepad controls to keyboard only while the login greeter exists. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define MAX_DEVS 32
static int devices[MAX_DEVS], ndev;

static bool greeter_active(void) {
    DIR *d = opendir("/proc"); struct dirent *e; char path[64], name[64]; FILE *f;
    if (!d) return false;
    while ((e = readdir(d))) {
        if (strspn(e->d_name, "0123456789") != strlen(e->d_name)) continue;
        snprintf(path, sizeof path, "/proc/%s/comm", e->d_name);
        f = fopen(path, "r");
        if (f && fgets(name, sizeof name, f) && !strcmp(strtok(name, "\n"), "plasma-login-greeter")) { fclose(f); closedir(d); return true; }
        if (f) fclose(f);
    }
    closedir(d); return false;
}
static int make_keyboard(void) {
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    struct uinput_setup setup = { .id = { .bustype = BUS_VIRTUAL, .vendor = 0x1d6b, .product = 0x4c47, .version = 1 } };
    strcpy(setup.name, "Ludus virtual keyboard");
    if (fd < 0 || ioctl(fd, UI_SET_EVBIT, EV_KEY) || ioctl(fd, UI_SET_KEYBIT, KEY_LEFT) || ioctl(fd, UI_SET_KEYBIT, KEY_RIGHT) || ioctl(fd, UI_SET_KEYBIT, KEY_ENTER) || ioctl(fd, UI_DEV_SETUP, &setup) || ioctl(fd, UI_DEV_CREATE)) return -1;
    return fd;
}
static void key(int out, int code, int value) {
    struct input_event ev = { .type = EV_KEY, .code = code, .value = value };
    write(out, &ev, sizeof ev); ev.type = EV_SYN; ev.code = SYN_REPORT; ev.value = 0; write(out, &ev, sizeof ev);
}
static bool is_gamepad(int fd) {
    unsigned long absbits[(ABS_MAX / (8 * sizeof(long))) + 1] = {0};
    unsigned long keybits[(KEY_MAX / (8 * sizeof(long))) + 1] = {0};
    ioctl(fd, EVIOCGBIT(EV_ABS, sizeof absbits), absbits); ioctl(fd, EVIOCGBIT(EV_KEY, sizeof keybits), keybits);
    return (absbits[ABS_HAT0X / (8*sizeof(long))] & (1UL << (ABS_HAT0X % (8*sizeof(long))))) || (keybits[BTN_GAMEPAD / (8*sizeof(long))] & (1UL << (BTN_GAMEPAD % (8*sizeof(long)))));
}
static void scan(void) {
    DIR *d = opendir("/dev/input"); struct dirent *e; char p[128]; int fd;
    for (int i = 0; i < ndev; ++i) close(devices[i]);
    ndev = 0;
    if (!d) return;
    while ((e = readdir(d)) && ndev < MAX_DEVS) {
        if (strncmp(e->d_name, "event", 5)) continue;
        snprintf(p, sizeof p, "/dev/input/%s", e->d_name); fd = open(p, O_RDONLY | O_NONBLOCK);
        if (fd >= 0 && is_gamepad(fd)) devices[ndev++] = fd; else if (fd >= 0) close(fd);
    }
    closedir(d);
}
int main(void) {
    int out = make_keyboard(), direction = 0, ticks = 0;
    if (out < 0) { perror("uinput"); return 1; }
    scan();
    for (;;) {
        struct pollfd pfds[MAX_DEVS]; for (int i=0;i<ndev;i++) pfds[i]=(struct pollfd){devices[i],POLLIN,0};
        int r = poll(pfds, ndev, 500);
        if (++ticks % 10 == 0) scan();
        if (r <= 0 || !greeter_active()) continue;
        for (int i=0;i<ndev;i++) if (pfds[i].revents & POLLIN) { struct input_event ev;
            while (read(devices[i], &ev, sizeof ev) == sizeof ev) {
                if (ev.type == EV_KEY && ev.code == BTN_SOUTH) key(out, KEY_ENTER, ev.value);
                if (ev.type == EV_ABS && (ev.code == ABS_HAT0X || ev.code == ABS_X)) {
                    int next = ev.value < 0 ? -1 : ev.value > 0 ? 1 : 0;
                    if (ev.code == ABS_X && (ev.value > -12000 && ev.value < 12000)) next = 0;
                    if (next != direction) { if (next) key(out, next < 0 ? KEY_LEFT : KEY_RIGHT, 1), key(out, next < 0 ? KEY_LEFT : KEY_RIGHT, 0); direction = next; }
                }
            }
        }
    }
}
