from settings import DEFAULT_CONFIG

def generate_config(dns='cloudflare'):
    DNS_SERVERS = {
        'cloudflare': '1.1.1.1, 2606:4700:4700::1111',
        'google': '8.8.8.8, 2001:4860:4860::8888',
        'adguard': '94.140.14.14, 2a10:50c0::ad1:ff'
    }
    
    return DEFAULT_CONFIG.format(dns=DNS_SERVERS[dns])

DEFAULT_CONFIG = """
[Interface]
PrivateKey = mIk2nsGpeBbECjw1ZPo+svm2maj5VAwue0fG/oJ8Bwk=
Address = 172.16.0.2, 2606:4700:110:8f9c:6051:85c2:19a4:ef13
DNS = {dns}

[Peer]
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = engage.cloudflareclient.com:2408
"""
