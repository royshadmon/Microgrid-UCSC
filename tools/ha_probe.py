import pexpect, sys

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJRXKmqSBHM1dIieO3JVaN5zX3OZQ33jpIhKJBwh2xcE hranjan@ucsc.edu"
HOST = "Microgrid@192.168.254.69"
PW = "manager123"

c = pexpect.spawn("ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null " + HOST,
                  timeout=60, encoding="utf-8")
i = c.expect(["continue connecting", "assword:", pexpect.EOF, pexpect.TIMEOUT])
if i == 0:
    c.sendline("yes")
    c.expect("assword:")
    i = 1
if i != 1:
    print("NO PASSWORD PROMPT")
    print(c.before)
    sys.exit(1)
c.sendline(PW)
j = c.expect([r"\$ ", r"# ", "assword:", pexpect.EOF, pexpect.TIMEOUT], timeout=40)
if j == 2:
    print("AUTH FAILED")
    sys.exit(1)
if j > 2:
    print("NO SHELL: " + str(c.before))
    sys.exit(1)
print("SHELL OK")

def run(cmd, timeout=180):
    c.sendline(cmd + "; echo __EN''D__")
    c.expect("__END__", timeout=timeout)
    out = c.before
    lines = [l.rstrip() for l in out.splitlines()]
    print("\n".join(lines[1:]))

run("mkdir -p ~/.ssh && chmod 700 ~/.ssh; grep -q hranjan ~/.ssh/authorized_keys 2>/dev/null || echo '" + KEY + "' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; echo KEY_OK")
print("--- identity ---")
run("whoami; hostname; uname -m")
print("--- sudo ---")
run("sudo -n true 2>/dev/null && echo SUDO_NOPASS || echo SUDO_NEEDS_PASS")
print("--- docker ---")
run("docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null | head")
print("--- config_entries search ---")
run("find /usr/share/hassio /home /config /opt /srv /var/lib/docker/volumes -maxdepth 8 -name core.config_entries 2>/dev/null | head")
c.sendline("exit")
