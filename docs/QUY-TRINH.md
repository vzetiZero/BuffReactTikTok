# Tài liệu quy trình — TikTok Comment Manager

> Cập nhật: 2026-09-29 · Trạng thái: **chạy được bản MVP**
> Mục đích tài liệu: ghi lại *logic đang triển khai*, *cái đã xong / đang làm / chưa làm*,
> và *repo tham khảo*, để không phải đoán lại logic khi mở lại dự án.

---

## 1. Bài toán

Quản lý nhiều tài khoản TikTok (đầu vào là **cookie** đã xuất sẽ sẵn), mỗi tài khoản
thực hiện **một hành động giống nhau trên một bình luận (`cid`) chỉ định** — chủ yếu
là **bấm tim (digg)**. Yêu cầu cốt lõi: chạy **đồng thời đa luồng**, và tốc độ
**scale theo số lượng tài khoản**.

Định dạng file đầu vào (`cokie.tik.txt`), mỗi dòng 1 tài khoản, phân tách bằng `|`:

```
user_id | username | email | password | msToken | device_id | email2 | cookie_string
```

> Cookie chứa `sessionid`, `sessionid_ss`, `sid_tt`, `sid_guard`, `ttwid`, `msToken`,
> `tt_csrf_token`, `uid_tt`… → **đủ để đăng nhập không cần mật khẩu**.

---

## 2. Kiến trúc đang áp dụng

Ba tầng, tách bạch trách nhiệm:

```
┌───────────────────────────────────────────────────────────────┐
│  TẦNG 1 · GUI THREAD (PySide6)                                │
│  MainWindow · AccountTableModel · AccountCellDelegate         │
│  Chỉ: vẽ bảng, nhận input, nhận signal, KHÔNG gọi mạng       │
└───────────────┬───────────────────────────────────────────────┘
                │ Signal(status / progress / log)  ← queued, tự nhảy về GUI thread
┌───────────────▼───────────────────────────────────────────────┐
│  TẦNG 2 · QThreadPool                                          │
│  Mỗi AccountTask = 1 tài khoản = 1 thread                      │
│  HttpBackend → TikTokClient (1 session curl_cffi riêng/account)│
│  Đây là nơi chạy song song thật sự                              │
└───────────────┬───────────────────────────────────────────────┘
                │ POST /signature (mỗi request)
┌───────────────▼───────────────────────────────────────────────┐
│  TẦNG 3 · SIDECAR KÝ (tiến trình Node, dùng chung)             │
│  tiktok-signature → X-Bogus + X-Gnarly + msToken               │
│  KHÔNG phải nằm trong Python, KHÔNG nhân bản theo thread      │
└───────────────────────────────────────────────────────────────┘
```

### 2.1. Vì sao tách vậy (lý do quyết định, không phải lựa chọn cụ thể)

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| TikTok bắt buộc ký request | Dùng sidecar Node | Port thuật toán `webmssdk` (ChaCha-XOR + TLV) sang Python rủi ro cao, vỡ mỗi lần TikTok đổi bản. Gọi 1 tiến trình Node dùng SDK thật = luôn đúng bản. |
| TLS fingerprint bị chặn | `curl_cffi` + `impersonate="chrome"` | `requests`/urllib có JA3/JA4 của Python → TikTok nhận ra ngay. `curl_cffi` giả đúng fingerprint Chrome. |
| Tránh nhân bản sidecar theo thread | 1 sidecar phục vụ N thread | Mỗi bản sidecar = 1 Chromium (~300 MB RAM). Nhân bản theo số account là tự tạn chết mình. |
| Sidecar là nút thắt (~12 sig/s) | Chấp nhận, có đường mở rộng | 1 account = 2 sig (check login + digg). 500 account ≈ 83s. Muốn nhanh hơn → chạy N sidecar ở N cổng. |
| Tránh 1 browser cho mọi account | HTTP thuần, mỗi account 1 session | 1 browser = 1 hàng đợi tuần tự, mất hết ý nghĩa đa luồng. Nhưng vẫn cần proxy/IP khác nhau để TikTok không nhận ra. |

### 2.2. Cân bằng tốc độ (ước tính, chế độ mặc định)

Mỗi account ở chế độ `like_cid`:
- 1 request kiểm tra đăng nhập (`/api/user/detail/`)
- 1 request thả tim (`/api/comment/digg/`)
- (tuỳ chọn) 1–2 request đọc lại comment để xác minh số like

→ **2–4 chữ ký / account.** Các phần này đều I/O-bound nên thread scale gần tuyến tính.
Trần thực tế do sidecar đặt ra, không phải do Python.

---

## 3. Luồng xử lý 1 tài khoản (chi tiết từng bước)

```
HttpBackend.run()
 │
 ├─ 0. Kiểm tra cookie có sessionid_ss + sid_tt không
 │      └─ không có → FAIL ngay, không tốn request
 │
 ├─ 1. Tạo TikTokClient
 │      ├─ session curl_cffi (impersonate chrome)
 │      ├─ nạp toàn bộ cookie của account vào domain .tiktok.com
 │      └─ đồng bộ User-Agent với fingerprint của sidecar  ← BẮT BUỘC
 │
 ├─ 2. GET /api/user/detail/?uniqueId=<username>
 │      └─ thành công → cột B ghi "✔ Thành công" + nickname
 │      └─ status_code ≠ 0 → FAIL kèm nghĩa mã lỗi
 │
 ├─ 3. Theo chế độ đã chọn:
 │
 │   [like_cid]  ← MẶC ĐỊNH
 │      ├─ POST /api/comment/digg/?aweme_id=..&cid=..&digg_type=1
 │      ├─ status_code == 0  → đọc lại comment, so sánh digg_count trước/sau
 │      └─ ghi kết quả: "♥ cid=… · like 244 → 245"
 │
 │   [find_like]
 │      ├─ GET /api/comment/list/?aweme_id=..&count=50   (phân trang)
 │      ├─ với mỗi comment có reply: GET /api/comment/list/reply/
 │      ├─ lọc theo target_text (không phân biệt hoa thường)
 │      └─ rồi gọi digg như trên
 │
 │   [reply_cid]
 │      └─ POST /api/comment/item/comment/publish/  (fallback: /publish/async/)
 │           body kèm comment_id = cid  → trả lời đúng bình luận đó
 │
 │   [check]
 │      └─ dừng ở bước 2
 │
 └─ 4. Trả TaskResult(status, note, comment_id, found, ok, code)
        └─ emit signal về GUI — worker KHÔNG tự update gì
```

### 3.1. Quy tắc bất di bất dịch về luồng (threading)

1. **Worker không bao giờ chạm widget hay model.** Chỉ `emit` signal.
2. `MainWindow` là nơi **duy nhất** gọi `model.update_row()`.
3. Cập nhật **theo `account.id`**, không theo chỉ số dòng — vì dòng sẽ bị sort/insert.
4. `stop()` dùng `threading.Event`, task đang chạy sẽ tự báo `SKIP`; task chưa bắt
   đầu cũng báo `SKIP` → **luôn đúng 1 tín hiệu cho mỗi task**, không treo bộ đếm.
5. Vì sao **không** dùng `QThreadPool.clear()`: task bị clear không bao giờ phát tín
   hiệu hoàn tất → bộ đếm kẹt → `finished` không bao giờ phát.

---

## 3.2. Tham số fingerprint — đối chiếu với DevTools

Request thật bạn gửi có 27 tham số riêng (không tính chữ ký). Bốn điều TikTok kiểm tra
chéo, thiếu hoặc sai một là request bị từ chối:

| Nhóm | Quy tắc | Nguồn |
|---|---|---|
| **Ngôn ngữ** | `app_language` = `browser_language` = `language` = `webcast_language`, và phải khớp tài khoản | `store-country-code=vn` → `vi-VN` |
| **Nền tảng** | `os` = `windows` ⇔ `browser_platform` = `Win32`, phải suy ra từ UA của sidecar | `_os_family(ua)` |
| **Phiên bản** | `browser_version` chứa đúng số Chrome trong UA | `_chrome_version(ua)` |
| **Múi giờ / vùng** | `tz_name` + `region` + `priority_region` khớp cookie | `Asia/Bangkok` + `VN` |

Hai chi tiết dễ sai đã sửa:

- **`verifyFp`** chính là cookie `s_v_web_id` (dạng `verify_xxx_yyy…`). Trước đây thiếu.
- **Header CSRF** tên đúng là `tt-csrf-token`, không phải `x-csrf-token` (cái sau bị bỏ qua).
  Ngoài ra `Referer` là **trang chủ theo locale** (`https://www.tiktok.com/vi-VN/`),
  không phải URL video.

`device_id` và `odinId` trên web là **số bão hòa 19 chữ số**. File cookie của bạn lưu
`device_id` dạng UUID (`9e5f94bc-e8a4-…`) — gửi UUID đi sẽ bị từ chối. Vì vậy
`_numeric_id()` chỉ nhận giá trị đúng kiểu số, còn lại bỏ trống để TikTok tự sinh.
Thiếu 2 tham số này vẫn chạy; gửi sai thì fail.

Chạy `python test_digg_url.py` để so 27 tham số với request thật của bạn.

---

## 3.3. Ba chữ ký trong URL

Request thật có **ba** tham số chữ ký, không phải hai:

| Tham số | Giá trị trong request của bạn | Ý nghĩa |
|---|---|---|
| `X-Bogus` | `1` | Giá trị đệm, chỉ là cách cơ sở tạo chữ ký |
| `X-Gnarly` | `MCeokLHWFSX14lJ…` | Chữ ký chính (ChaCha-XOR + TLV) |
| `X-Dynosaur` | `M8ln-splcyYynbdZO/…` | Chữ ký phụ |

Cả ba đều do sidecar sinh. Ứng dụng **không tự dịch** bất kỳ chữ ký nào — chỉ gửi URL
trần cho sidecar và dùng lại `signed_url` trả về. Nếu TikTok đổi thuật toán, chỉ cần
cập nhật sidecar, không phải sửa code Python.

---

### 3.4. Danh sách lớn: tìm kiếm + lọc + sắp xếp + phân trang

Với hàng chục nghìn tài khoản, bảng phải vừa nhanh vừa dùng được. Ba quyết định:

**Không dùng `QSortFilterProxyModel`.** Proxy này gọi `data()` hai lần cho mỗi ô và
tạo lại toàn bộ chỉ số khi lọc/sắp xếp — với 50 000 dòng thì mỗi lần gõ ký tự là
vài trăm mili giây. Thay vào đó model giữ hai list:

```
_rows   toàn bộ tài khoản (nguồn chân lý, không bao giờ đổi)
_view   sau khi lọc + sắp xếp
```

Chỉ trang hiện tại của `_view` được đưa ra bảng. Lọc/sắp xếp gọi
`beginResetModel()` / `endResetModel()` một lần, rồi `rowCount()` trả về đúng số
dòng của trang — vẫn là con số nhỏ.

**Cache chuỗi tìm kiếm.** `_haystack()` gộp username + email + id + proxy + trạng
thái + ghi chú thành một chuỗi thường, lưu theo `account.id` ngay khi nạp. Nếu
không cache, mỗi lần gõ phải `lower()` lại hàng chục nghìn chuỗi. Nội dung hiển
thị có thể đổi (trạng thái, ghi chú) nhưng cache được xây lại khi nạp lại danh
sách — chấp nhận được vì những trường đó không nằm trong từ khoá tìm kiếm phổ
biến.

**Gõ có trễ 250 ms** (`QTimer` single-shot). Gõ liên tục chỉ lọc ở lần gõ cuối,
không lọc lại 20 lần cho một từ.

### 3.4.1. Ba loại "tick" — phân biệt rõ để không nhầm

| Nút | Phạm vi | Dùng khi |
|---|---|---|
| Tick tất cả / Bỏ tick | **Toàn bộ** danh sách | Muốn chạy hết |
| Trang này + / − | Chỉ trang đang xem | Đang duyệt từng trang, chỉ chọn vài |
| **Tick kết quả lọc** | Mọi tài khoản **khớp lọc** | Lọc "Thiếu phiên" rồi tick hết nhóm — nhanh hơn tick từng trang khi danh sách lớn |

Nút CHẠY luôn dùng `selected_accounts()` trên toàn bộ danh sách, **không** giới hạn
theo trang hay bộ lọc đang xem — tránh tình trạng lọc rồi tưởng chỉ chạy trang đang xem.

### 3.4.2. Số thứ tự

Số thứ tự tính trên `_view` (tập đang lọc), nên liên tục qua các trang và khớp
với những gì mắt thấy. Khi không lọc thì trùng với thứ tự gốc trong file cookie.

---

## 4. Trạng thái triển khai

### 4.1. ĐÃ XONG ✅

| # | Hạng mục | File | Ghi chú |
|---|---|---|---|
| 1 | Parse file cookie `\|` (8 trường) | `core/parser.py` | Tự sinh id, tự bỏ dòng hỏng, tự lấy `aweme_id` từ URL |
| 2 | Phát hiện cookie còn sống | `core/models.py` | Kiểm tra `sessionid_ss` + `sid_tt`; đọc hạn từ `sid_guard` |
| 3 | Model 2 cột A/B | `core/models.py` | Cột A = thông tin, cột B = trạng thái |
| 4 | Delegate vẽ 2 cột | `ui/delegates.py` | Ô tick + username/email 2 dòng, màu theo trạng thái |
| 5 | Đa luồng QThreadPool | `core/runner.py` | Mỗi account 1 task; dừng an toàn; không treo |
| 6 | Client HTTP giả TLS Chrome | `core/tiktok.py` | `curl_cffi`, CSRF, msToken, retry, giải thích mã lỗi |
| 7 | Thả tim theo `cid` | `core/tiktok.py` | `POST /api/comment/digg/`, `cid` trong **query string** |
| 8 | Tìm reply theo từ khoá | `core/tiktok.py` | Phân trang comment/list + reply/list |
| 9 | Trả lời bình luận | `core/tiktok.py` | `publish/` + fallback `publish/async/` |
| 10 | Xác minh số like trước/sau | `core/backends/http_backend.py` | Phát hiện trường hợp đã thả tim rồi |
| 11 | Client sidecar ký | `core/signer.py` | `/health`, `/signature`, `/restart`, cache navigator |
| 12 | Backend giả lập | `core/backends/mock_backend.py` | Test GUI + đa luồng không cần mạng |
| 13 | Giao diện 4 tab + form CID | `ui/main_window.py` | Quản lý / Tác vụ / Chi tiết / Cài đặt |
| 13a | Style chung | `ui/style.py` | Bảng, nút, tab, nhật ký — màu navy/đỏ/xanh |
| 13b | Panel chi tiết | `ui/detail_panel.py` | Thẻ bài viết, thẻ tài khoản, thẻ tổng quan |
| 14 | Test đa luồng | `smoke_test.py` | 7 account × 4 luồng |
| 15 | **Tab "Cài đặt"** | `ui/settings_tab.py` | Kho proxy, phân phối, cổng VPN Express, cấu hình chung |
| 16 | **Lớp proxy** | `core/proxy.py` | Parse 5 định dạng, 4 chế độ gán, xoay vòng, kiểm tra song song |
| 17 | **Proxy per-account** | `core/runner.py` | Task đọc `account.proxy`; đổi proxy khi bị chặn IP |
| 18 | **Lưu cấu hình** | `core/settings.py` | JSON, tự lưu khi đóng app |
| 19 | **Cầu nối luồng** | `core/gui_bridge.py` | Đưa callback từ thread nền về GUI thread |
| 20 | **Fingerprint khớp DevTools** | `core/tiktok.py` | Ngôn ngữ từ cookie, `verifyFp`, `history_len=8`, header `tt-csrf-token` |
| 21 | Test proxy | `test_proxy.py` | 25/25 PASS |
| 22 | Test URL digg | `test_digg_url.py` | So 27 tham số với request thật → HỢP LỆ |
| 23 | Tìm kiếm / lọc / sắp xếp | `core/models.py` | 8 bộ lọc, sắp xếp 3 kiểu, cache chuỗi, gõ trễ 250ms |
| 24 | Proxy hệ thống | `core/proxy.py` | WinINET / scutil / gsettings / biến môi trường |
| 25 | Test tìm kiếm | `test_search.py` | 37/37 PASS, 5000 dòng: lọc 9ms |
| 26 | Test phân trang | `test_paging.py` | 23/23 PASS |

### 4.2. ĐANG LÀM 🔄

| # | Hạng mục | Mục tiêu | Vướng |
|---|---|---|---|
| 1 | Tích hợp sidecar thật | Chạy `npm start`, xác nhận `status_code: 0` | Chưa có Node trong máy dev — đây là bước chặn duy nhất còn lại |
| 2 | Xác minh số like | Đọc `digg_count` sau khi thả tim | Cần request xác minh; mỗi lần = 2–4 chữ ký, tốn gấp đôi |
| 3 | Cấu hình `device_id` / `odinId` | Cho phép nhập tay 2 số này | File cookie lưu UUID ở `device_id`, web cần số bão hòa 19 chữ số |

### 4.3. CHƯA LÀM ⬜

| # | Hạng mục | Ghi chú |
|---|---|---|
| 1 | Proxy gắn riêng cho từng account | Hiện phân phối tự động; thêm bảng `account → proxy` để gán tay |
| 2 | Bảng lưu trạng thái (DB) | SQLite: cookie, lịch sử đã like, tránh like trùng |
| 3 | Lịch chạy tự động | Cron nội bộ: quét bình luận mới rồi like |
| 4 | Bảng từ khóa + nhiều cid | Like hàng loạt nhiều cid theo bảng |
| 5 | Chống trùng cid | Đã like cid này rồi → bỏ qua, tiết kiệm request |
| 6 | Đo & hiển thị throughput | req/s, độ trễ trung bình, hàng đợi sidecar |
| 7 | Chế độ dự phòng qua CDP | Điều khiển Chrome thật bằng DevTools Protocol khi chữ ký hỏng |
| 8 | Mã hoá mật khẩu proxy trong file cấu hình | Hiện lưu plaintext trong `settings.json` |
| 9 | Đóng gói `.exe` | PyInstaller |

---

## 4.4. Hệ thống proxy

### 4.4.1. Vì sao proxy per-account là bắt buộc

Nhiều tài khoản xuất phát từ cùng một IP là dấu hiệu bất thường rõ nhất với TikTok.
Đa luồng chỉ làm vấn đề **nặng thêm** — càng chạy nhanh thì càng nhiều request từ
cùng một IP trong thời gian ngắn. Đây là thứ mấy tổng tiền (đa luồng) không giải quyết được.

### 4.4.2. Luồng xử lý

```
Tab Cài đặt
  ├─ nhập / nạp danh sách proxy ──► ProxyPool.load()  (parse, bỏ dòng rác)
  ├─ chọn chế độ gán ─────────────► ProxyPool.assign()
  │     ├─ round_robin : account thứ i ← proxy thứ (i mod N)
  │     ├─ random      : bốc ngẫu nhiên
  │     ├─ fixed       : giữ nguyên lần trước
  │     └─ gateway     : 1 cổng VPN Express, mỗi account 1 session
  └─ kết quả gán ────────────────► account.proxy + account.proxy_label
                                    (hiện trên cột A của bảng Tài khoản)

Khi chạy
  HttpBackend.run()  →  proxy = account.proxy  (ưu tiên) hoặc proxy chung
  Khi TikTok trả mã lỗi IP (8, 10202, 10221, 10222, 350002)
     └─ AccountTask vòng lặp thử lại → ProxyPool.rotate() → proxy kế tiếp
```

### 4.4.3. Cổng VPN Express — cách hoạt động

Thay vì mua N địa chỉ IP, VPN Express cho một **cổng** (`gate.vpnexpress.net:10000`).
Địa chỉ IP thật nằm trong **username**, theo mẫu:

```
{user}-country-{country}-session-{session}:{pass}@{host}:{port}
```

`{session}` là mã ngẫu nhiên, mỗi giá trị một IP. Nhờ vậy:

| Nhu cầu | Cách làm |
|---|---|
| Mỗi account một IP | Mỗi account một `session` khác nhau (tính bằng SHA1 từ id account → ổn định giữa các lần chạy) |
| Đổi IP khi bị chặn | Cấp `session` **mới** (biến `fresh=True` trong `GatewayConfig.build`) |
| 500 account, 1 cổng | 500 session khác nhau, vẫn chỉ 1 cấu hình proxy |

Đây là lý do ứng dụng này hỗ trợ cổng ngay từ đầu thay vì chỉ nhận danh sách IP tĩnh:
500 IP tĩnh tốn 500 dòng cấu hình và bán nhanh hết, còn 1 cổng thì không.

### 4.4.4. So sánh "đã đổi proxy"

Cần cẩn thận: dải IP rộng thường chỉ khác **mật khẩu** ở mỗi lần truy cập, IP thật vẫn
là IP cũ. Nếu so sánh bằng cả URL thì vòng lặp đổi proxy sẽ không bao giờ thoát.
Vì vậy `ProxyProfile.fingerprint()` chỉ so `scheme + host + port`, cố ý bỏ qua
`username`/`password`.

### 4.4.5. Định dạng proxy nhận được

```
1.2.3.4:8080                              IP:port
1.2.3.4:8080:user:pass                    IP:port:user:pass
user:pass@1.2.3.4:8080                    user:pass@IP:port
socks5://9.9.9.9:1080                     có scheme
# ghi chú                                    bỏ qua
```

Mật khẩu chứa `:` vẫn đúng (phần sau dấu `:` thứ 3 được nối lại). Mọi nơi hiển thị
đều che mật khẩu thành `***`; chỉ chỗ dùng thật mới giữ bản đầy đủ.

---

## 5. Bảng tra mã lỗi TikTok

| `status_code` | Nghĩa | Xử lý |
|---|---|---|
| `0` | OK | — |
| `8` | Rate limit | Tăng trễ, giảm luồng |
| `10202` / `10221` | Bị chặn bot, cần xác minh | Đổi IP/proxy, giảm tần suất |
| `10222` | IP bị chặn | Đổi proxy |
| `200004` | Video không tồn tại | Kiểm tra `aweme_id` |
| `200005` | Bình luận không tồn tại | Kiểm tra `cid` |
| `200013` | Chưa đăng nhập / hết phiên | Cookie hết hạn → cần login tay |
| `200015` | Đã bình luận rồi | Bỏ qua |
| `200034` | Đã thả tim rồi | Bỏ qua (coi như thành công) |
| `350002` | Bình luận quá nhiều | Giảm tần suất |

---

## 6. Repo GitHub tham khảo

### 6.1. Bắt buộc — phần ký request

| Repo | Vai trò | Ghi chú |
|---|---|---|
| **[carcabot/tiktok-signature](https://github.com/carcabot/tiktok-signature)** | **Sidecar ký — repo này là xương sống hệ thống** | Chạy Puppeteer + inject `webmssdk` thật. Có `/signature` (khuyên dùng), `/fetch` (dự phòng), `/health`, `/restart`. Có sẵn mẫu URL đầy đủ cho nhiều endpoint trong `examples/`. Benchmark ~12 sig/s, 84ms. |
| **[carcabot/tiktok-xgnarly-decoded](https://github.com/carcabot/tiktok-xgnarly-decoded)** | Tài liệu thuật toán `X-Gnarly` | Giải mã TLV 16 trường + ChaCha-style cipher. Dùng để **hiểu** vì sao chữ ký phụ thuộc UA, và nếu sau này muốn port sang Python thì bắt đầu từ đây. Bản tham chiếu: `5.1.3-ZTCA`. |
| **[autodev/tiktok-research](https://autodev.blog/posts/tiktok-research-article/)** | Bài phân tích reverse-engineering web protection | Giải thích luồng `msToken` → `X-Bogus`, tại sao cả 3 điều kiện (TLS + chữ ký + cookie) đều bắt buộc. |

### 6.2. Tham khảo — thư viện client

| Repo | Vai trò | Trạng thái |
|---|---|---|
| **[Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2)** | Thư viện TikTok Python đầy đủ nhất, có xử lý chữ ký | Tham khảo **rất tốt** cho endpoint + tham số. Có thể thay cả `core/tiktok.py`. |
| **[davidteather/TikTok-Api](https://github.com/davidteather/TikTok-Api)** | Wrapper API phổ biến nhất | Dễ đọc để đối chiếu tên tham số, nhưng phụ thuộc Playwright → chậm, không hợp mục tiêu tốc độ. |
| **[unclecode/crawl4ai](https://github.com/unclecode/crawl4ai)** | Browser cho headless | Không dùng ở đây, chỉ tham khảo nếu cần nhánh dự phòng. |
| **[lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi)** | HTTP client giả TLS | **Đang dùng.** Cũng có `AsyncSession` nếu sau này muốn đổi sang asyncio. |

### 6.3. Công cụ phụ trợ

| Công cụ | Dùng để |
|---|---|
| **Fiddler / Charles / mitmproxy** | Bắt và soi lại request thật từ trình duyệt để đối chiếu endpoint/tham số khi API đổi. |
| **Chrome DevTools → Network** | Xem chính xác `cid`, `digg_type`, header CSRF mà web gửi đi. |
| **curl** | Test nhanh 1 endpoint ngoài app. |

---

## 7. Vài điều nên biết trước khi mở rộng

**Về tốc độ.** Muốn nhanh hơn theo đúng nghĩa "cùng số lượng", thứ tự nên làm:
1. Tách luồng kiểm tra đăng nhập khỏi luồng thả tim (bỏ `/api/user/detail/` nếu không cần) → giảm 50% số chữ ký.
2. Tắt xác minh số like → giảm thêm ~50%.
3. Chạy 2–3 sidecar ở các cổng khác nhau, chia tải round-robin.
4. Cuối cùng mới tăng số luồng Python — phần này thường **không** phải nút thắt.

Còn nếu vẫn chậm, nút thắt gần như chắc chắn là **IP**: nhiều account trên một IP là
dấu hiệu bất thường rõ nhất với TikTok. Khi đó cần proxy mỗi account, và đó là
việc mà **không giải quyết được bằng đa luồng**.

**Về an toàn dữ liệu.** File cookie chứa phiên đăng nhập thật, tương đương mật khẩu.
`cokie.tik.txt` trong thư mục này là dữ liệu thật — đừng commit lên git, đừng chia sẻ,
và xoá khi không dùng nữa. File cấu hình `settings.json` cũng chứa **mật khẩu proxy ở
dạng plaintext**; hãy coi nó cùng mức nhạy cảm với cookie.

**Về pháp lý.** Tự động hoá trên TikTok vi phạm Điều khoản dịch vụ và có thể khiến
tài khoản bị khoá. Chỉ nên dùng trên tài khoản của chính bạn, với khối lượng nhỏ,
và bạn chịu trách nhiệm về việc sử dụng.
