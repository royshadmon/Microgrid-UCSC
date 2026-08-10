import sys, re, json, urllib.request, urllib.parse, http.cookiejar

base = "http://192.168.254.48"
email = sys.argv[1]
password = sys.argv[2]

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "Mozilla/5.0")]

html = op.open(base + "/sign_in", timeout=20).read().decode("utf-8", "replace")
print("SIGNIN PAGE bytes=" + str(len(html)))
names = sorted(set(re.findall(r'name="([^"]+)"', html)))
print("FIELDS=" + str(names))
acts = sorted(set(re.findall(r'action="([^"]+)"', html)))
print("ACTIONS=" + str(acts))

tok = re.findall(r'name="_csrf_token"[^>]*value="([^"]+)"', html)
if not tok:
    tok = re.findall(r'value="([^"]+)"[^>]*name="_csrf_token"', html)
print("CSRF=" + ("yes" if tok else "no"))

data = {"_csrf_token": tok[0] if tok else "", "user[email]": email, "user[password]": password}
action = acts[0] if acts else "/sign_in"
if not action.startswith("http"):
    action = base + action

req = urllib.request.Request(action, data=urllib.parse.urlencode(data).encode(), method="POST")
try:
    r = op.open(req, timeout=20)
    body = r.read().decode("utf-8", "replace")
    print("POST -> " + str(r.status) + " " + r.geturl())
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    print("POST -> HTTPError " + str(e.code))

print("COOKIES=" + str([c.name for c in cj]))
low = body.lower()
print("LOGIN_OK=" + str("sign_in" not in low or "invalid" not in low))
if "invalid" in low or "incorrect" in low:
    print("!! credential rejected")

for path in ["/configuration/mqtt", "/mqtt", "/configuration"]:
    try:
        h = op.open(base + path, timeout=20)
        t = h.read().decode("utf-8", "replace")
        print("=== " + path + " -> " + str(h.status) + " " + h.geturl() + " bytes=" + str(len(t)))
        if "mqtt" in t.lower():
            for m in re.findall(r'<input[^>]+>', t):
                if any(k in m.lower() for k in ["user", "pass", "port", "host", "broker", "topic", "enable"]):
                    print("   " + m.strip()[:220])
    except Exception as ex:
        print("=== " + path + " -> " + repr(ex)[:120])
