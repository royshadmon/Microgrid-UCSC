import re, urllib.request, http.cookiejar
base = "http://192.168.254.48"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "Mozilla/5.0")]
op.open(base + "/sign_in", timeout=20).read()
t = op.open(base + "/configuration/mqtt", timeout=20).read().decode("utf-8", "replace")
print("--- INPUTS ---")
for m in re.findall(r'<input[^>]+>', t):
    print(m.strip()[:250])
print("--- SELECTED/CHECKED ---")
for m in re.findall(r'<option[^>]*selected[^>]*>[^<]*</option>', t):
    print(m.strip()[:150])
print("--- TEXT ---")
txt = re.sub(r'<script.*?</script>', ' ', t, flags=re.S)
txt = re.sub(r'<[^>]+>', ' ', txt)
txt = re.sub(r'\s+', ' ', txt).strip()
print(txt[:1500])
