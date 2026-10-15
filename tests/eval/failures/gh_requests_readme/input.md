# Requests

[![Version](https://img.shields.io/pypi/v/requests.svg?maxAge=86400)](https://pypi.org/project/requests/)
[![Supported Versions](https://img.shields.io/pypi/pyversions/requests.svg)](https://pypi.org/project/requests)
[![Downloads](https://static.pepy.tech/badge/requests/month)](https://pepy.tech/project/requests)
[![Contributors](https://img.shields.io/github/contributors/psf/requests.svg)](https://github.com/psf/requests/graphs/contributors)
[![Documentation](https://readthedocs.org/projects/requests/badge/?version=latest)](https://requests.readthedocs.io)

**Requests** is a simple, yet elegant, HTTP library.

```python
>>> import requests
>>> r = requests.get('https://httpbin.org/basic-auth/user/pass', auth=('user', 'pass'))
>>> r.status_code
200
>>> r.headers['content-type']
'application/json; charset=utf8'
>>> r.encoding
'utf-8'
>>> r.text
'{"authenticated": true, ...'
>>> r.json()
{'authenticated': True, ...}
```

Requests allows you to send HTTP/1.1 requests extremely easily. There’s no need to manually add query strings to your URLs, or to form-encode your `PUT` & `POST` data — but nowadays, just use the `json` method!

Requests is one of the most downloaded Python packages today, pulling in around `300M downloads / week` — according to GitHub, Requests is currently [depended upon](https://github.com/psf/requests/network/dependents?package_id=UGFja2FnZS01NzA4OTExNg%3D%3D) by `4,000,000+` repositories.

## Installing Requests and Supported Versions

Requests is available on PyPI:

```console
$ python -m pip install requests
```

Requests officially supports Python 3.10+.

## Supported Features & Best–Practices

Requests is ready for the demands of building robust and reliable HTTP–speaking applications, for the needs of today.

- Keep-Alive & Connection Pooling
- International Domains and URLs
- Sessions with Cookie Persistence
- Browser-style TLS/SSL Verification
- Basic & Digest Authentication
- Familiar `dict`–like Cookies
- Automatic Content Decompression and Decoding
- Multi-part File Uploads
- SOCKS Proxy Support
- Connection Timeouts
- Streaming Downloads
- Automatic honoring of `.netrc`
- Chunked HTTP Requests

## Cloning the repository

When cloning the Requests repository, you may need to add the `-c
fetch.fsck.badTimezone=ignore` flag to avoid an error about a bad commit timestamp (see
[this issue](https://github.com/psf/requests/issues/2690) for more background):

```shell
git clone -c fetch.fsck.badTimezone=ignore https://github.com/psf/requests.git
```

You can also apply this setting to your global Git config:

```shell
git config --global fetch.fsck.badTimezone ignore
```

---

[![Kenneth Reitz](https://raw.githubusercontent.com/psf/requests/main/ext/kr.png)](https://kennethreitz.org) [![Python Software Foundation](https://raw.githubusercontent.com/psf/requests/main/ext/psf.png)](https://www.python.org/psf)


## Contacts

- **Applicant: Marcus K. Whitfield, date of birth 05/01/1967**
- **Phone: +44 20 7465 4862  Email: marcus.whitfield74@demo-mail.example.com**
- **Card 5500 3725 8998 4375, passport no. 703370277**
- **SSN 176-30-5296; alt. contact Castellanos, Yuki**
- **Halcyon Dynamics, 3119 Fenwick Street, Halifax**
- **Wire to IBAN GB76NWBK81330989540668, attn Elena C. Haverford**
- **Customer: Grace Delacroix <billing24@halcyon-demo.example.org> tel (415) 555-7249**
- **Billing address: 1010 Brambleton Road, Halifax**

| Name | Phone | Email | SSN | Passport | Address |
|---|---|---|---|---|---|
| Marcus K. Whitfield | +44 20 7465 4862 | marcus.whitfield74@demo-mail.example.com | 176-30-5296 | 703370277 | 3119 Fenwick Street, Halifax |
| Yuki M. Castellanos | (415) 555-7249 | billing24@halcyon-demo.example.org | 250-22-2811 | E94379309 | 1010 Brambleton Road, Halifax |
| Elena C. Haverford | +1-212-555-3533 | ehaverford191@corp-demo.example.net | 176-30-5296 | 703370277 | 1812 Calloway Court, Halifax |

Ship to 1812 Calloway Court, Halifax, contact Marcus K. Kowalczyk +1-212-555-3533
Witness: Yuki Castellanos, passport E94379309, born July 26, 1965
Server 10.31.134.53 (fallback 172.16.27.164), admin ehaverford191@corp-demo.example.net
token = sk_live_291061Zq50135948Xw
password: Rv353!kd9611Pm
Blue Harbor Capital and Orchard Lane Partners signed by Grace S. Delacroix, SSN 250-22-2811
Card on file 4111 1315 1793 8699, phone +49 30 744974

```
password: Rv353!kd9611Pm
Blue Harbor Capital and Orchard Lane Partners signed by Grace S. Delacroix, SSN 250-22-2811
Card on file 4111 1315 1793 8699, phone +49 30 744974
```
This agreement is made between Halcyon Dynamics (3119 Fenwick Street, Halifax) represented by Elena C. Haverford and Marcus K. Whitfield, born 05/01/1967, passport 703370277, residing at 1010 Brambleton Road, Halifax.
Payments go to IBAN GB76NWBK81330989540668. Send notices to billing24@halcyon-demo.example.org or call +44 20 7465 4862. Copy Grace Delacroix (SSN 250-22-2811) on every invoice.
Hi Yuki, please charge card 5500 3725 8998 4375 for Orchard Lane Partners; my cell is +1-212-555-3533 and my email ehaverford191@corp-demo.example.net. Regards, Marcus K. Kowalczyk.

[mail](mailto:marcus.whitfield74@demo-mail.example.com)
