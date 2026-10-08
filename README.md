# TikTok Comment Manager

Desktop app (PySide6) quản lý nhiều tài khoản TikTok bằng **cookie**, chạy **đa luồng**
để thả tim / trả lời hàng loạt trên một bình luận chỉ định.

Tài liệu đầy đủ về logic và trạng thái: **[docs/QUY-TRINH.md](docs/QUY-TRINH.md)**

---

## Cài đặt từ đầu (máy mới)

Yêu cầu: **Python 3.9+**, **Node.js 18+**, **Git**, và khoảng **1.2 GB đĩa trống**.

### Bước 1 — Cài Node.js (bắt buộc)

| OS | Cách |
|---|---|
| Windows | <https://nodejs.org/> → bản `.msi` **LTS** → cài đặt mặc định |
| macOS | `brew install node`, hoặc tải bản `.pkg` LTS từ nodejs.org |
| Linux | `sudo apt install nodejs npm` (kiểm tra lại bản ≥ 18) |

> **Cài xong phải đóng rồi mở lại terminal.** Cửa sổ đang mở vẫn giữ
> `PATH` cũ, nên `node` sẽ không được nhận ra. Đây là nguyên nhân phổ biến
> nhất gây lỗi "không tìm thấy Node.js" dù đã cài.

Kiểm tra: gõ `node -v` → phải ra `v18.x` trở lên.

### Bước 2 — Lấy mã nguồn

```bash
git clone https://github.com/vzetiZero/BuffReactTikTok.git
cd BuffReactTikTok
```

Đặt tên thư mục **không có dấu cách và dấu tiếng Việt** (ví dụ đừng đặt là
`dụ an`) — các script và đường dẫn Node xử lý kém trường hợp này.

### Bước 3 — Cài thư viện + sidecar (một lệnh)

**Windows**

```bat
setup.bat
```

**macOS / Linux**

```bash
chmod +x setup.sh install.sh start.sh signer.sh
./setup.sh
```

`setup` làm hết: kiểm tra Python → kiểm tra Node.js → tạo `.venv` và cài
`PySide6`, `curl_cffi`, `requests` → tải sidecar + Chromium → kiểm tra file
cookie, rồi in ra các bước còn lại.

Cần Internet. Lần đầu tải Chromium mất vài phút.

### Bước 4 — Chuẩn bị file cookie

**Bước này phải tự làm, clone không có sẵn.** File cookie chứa thông tin đăng
nhập đầy đủ nên bị loại khỏi git có chủ đích.

Copy file cookie của bạn vào thư mục vừa clone, đặt tên `cokie.tik.txt`.
Định dạng — mỗi dòng một tài khoản, 8 trường phân tách bằng `|`:

```
user_id | username | email | password | msToken | device_id | email2 | cookie_string
```

Cookie lấy từ DevTools trình duyệt: đăng nhập TikTok → F12 → tab
**Application** → **Cookies** → `https://www.tiktok.com` → copy toàn bộ
thành một dòng `k=v; k2=v2` vào trường cuối.

### Bước 5 — Bật sidecar ký

Sidecar là **tiến trình Node riêng** lắng nghe ở `http://127.0.0.1:8080`.
Có hai cách bật:

**Cách 1 — bấm trong app (tiện nhất).** Mở app, bấm nút **Bật sidecar** ở
thanh dưới. App tự mở tiến trình và tự hỏi `/health` mỗi 2 giây cho tới khi
thanh dưới hiện `sidecar ✓ … chữ ký`.

**Cách 2 — mở cửa sổ riêng.** Windows: bấm đúp `signer.bat`.
macOS/Linux: `./signer.sh`. Cửa sổ này **phải để mở** suốt khi chạy.

> Sidecar **không cần "đăng ký"** gì cả. Nó chỉ là tiến trình Node nghe ở
> cổng 8080 trên chính máy bạn, app tự kết nối vào. Nếu thấy *"Chưa có sidecar
> ký"* nghĩa là tiến trình đó chưa chạy — bấm **Bật sidecar**, hoặc bấm
> **Kiểm tra lại** sau khi đã mở cửa sổ riêng.

Phải bật sidecar **trước khi bấm CHẠY**. Mở app rồi bật sidecar hay ngược
lại đều được, miễn là sidecar phải sống lúc bấm CHẠY.

> **Dung lượng:** Chromium ~390 MB + `node_modules` ~77 MB + `.venv` ~660 MB
> ≈ **1.1 GB**. Puppeteer còn tải thêm `chrome-headless-shell` (~255 MB) mà
> sidecar **không dùng** — bỏ được nếu bạn cần tiết kiệm chỗ:
> ```bat
> set PUPPETEER_SKIP_DOWNLOAD=true
> npm install
> npx puppeteer browsers install chrome
> ```

### Bước 6 — Mở app

**Windows**

```bat
start.bat
```

**macOS / Linux**

```bash
./start.sh
```

Trong app:

1. Bấm **Bật sidecar** ở thanh dưới → đợi tới khi hiện `sidecar ✓`.
   (Bỏ qua bước này nếu bạn đã mở `signer.bat` / `./signer.sh` ở cửa sổ
   riêng rồi. Nếu bật từ cửa sổ riêng thì bấm **Kiểm tra lại** để app biết.)
2. Bấm **📂 Nạp cookie** → chọn `cokie.tik.txt`.
3. (Tùy chọn) Chuột phải vào bảng → **Dọn nhanh** để loại tài khoản hỏng.
4. Dán danh sách `cid` vào ô **Danh sách cid** ở tab **Tác vụ**.
5. Tick tài khoản → đặt **Số luồng** → bấm **▶ CHẠY**.

### Cài xong thì những lần sau

```bat
start.bat          :: mở app
setup.bat          :: KHÔNG cần chạy lại — chỉ khi máy mới hoặc git pull xong
git pull           :: lấy bản cập nhật
```

Mỗi lần mở app: bấm **Bật sidecar** → nạp cookie (tự nhớ lần trước) → CHẠY.

Lần sau app **tự nhớ** danh sách tài khoản đã nạp, nên không cần chọn file
cookie nữa.

### Cài cho nhiều máy

Cài trên **một** máy đã có Node + sidecar chạy được, rồi copy toàn bộ thư mục
sang máy khác — `tiktok-signature/` và `.venv/` đều **không** nằm trong git
(`.gitignore`) nên phải copy riêng, hoặc chạy lại `install.bat` + `signer.bat`
trên mỗi máy.

### Xem nhanh

| Muốn | Dùng gì |
|---|---|
| Xem giao diện, không cần mạng | Backend = `mock`, bấm **Thử 1 tài khoản** |
| Dọn file cookie, không cần Node | Chuột phải → **Dọn nhanh** |
| Thả tim thật | Cần sidecar + proxy xoay IP |
| Kiểm tra tài khoản còn sống | Chuột phải → **Kiểm tra trạng thái** |

---

## Dùng nhanh

1. **Nạp file cookie** → file 1 dòng/tài khoản, phân tách bằng `|`:

   ```
   user_id | username | email | password | msToken | device_id | email2 | cookie_string
   ```

   Lần sau mở app sẽ **tự nạp lại**, không phải chọn file nữa.

2. Tick những tài khoản muốn dùng (mặc định tick tự động những cái còn phiên).

3. Kiểm tra tài khoản còn sống không — **chuột phải vào bảng**:

   | Mục menu | Tác dụng |
   |---|---|
   | Kiểm tra trạng thái: `<username>` | kiểm tra 1 tài khoản |
   | Kiểm tra *n* dòng chọn / cả trang / tất cả đã tick | kiểm tra nhóm |
   | **Dọn nhanh** | chỉ đọc cookie, **không gọi mạng**, không cần sidecar |
   | **Bỏ tick những tài khoản đã die** | bỏ tick hàng loạt tài khoản hỏng |

   Kết quả hiện ở **cột C · Status**: `● Sống` / `✖ Die` / `⌛ Hết hạn` / `? Không rõ`.
   Màu `? Không rõ` = bị TikTok chặn IP, **không phải** cookie chết — cần proxy để
   kiểm tra chính xác. Lọc nhanh bằng combo **“Status: còn sống”** / **“Status: đã die”**.

4. Dán danh sách **`cid`** vào ô **Danh sách cid** — mỗi dòng một id
   (cũng nhận phân tách bằng dấu phẩy):

   ```
   7690897576899658504
   7654223771003994898
   ```

   Bấm **▶ CHẠY**: chạy hết đàn tài khoản cho cid đầu tiên, rồi **tự chuyển sang
   cid kế tiếp** — log kiểu `▶ cid 2/5: …`. Bấm **■ DỪNG** giữa chừng sẽ xoá
   luôn các cid còn lại trong hàng đợi.

   Không cần `aweme_id` — endpoint `/api/comment/digg/` chỉ cần `cid`.

5. Đặt **Số luồng**, rồi bấm **▶ CHẠY**.

Bảng gồm 3 cột: **A** = thông tin tài khoản, **B** = kết quả lần chạy vừa rồi
(ví dụ `♥ cid=… · like 244 → 245`), **C** = sức khoẻ tài khoản.

---

## 💡 Bao nhiêu luồng?

Nút **Số luồng** = số request TikTok chạy song song. Tăng dần tới khi đồng hồ tốc
độ **không tăng thêm nữa** — đó là chỗ trần thật của bạn.

| Máy | Gợi ý |
|---|---|
| 4 nhân | 15–20 |
| 8 nhân | 30–40 |
| 10–12 nhân | 40–60 |
| **M3 Pro 14" (12 nhân)** | **40–50**, thử 60 nếu đồng hồ vẫn tăng |

Nhưng lưu ý: **trần thường không nằm ở máy**. Phần Python phân phối được
~5.800 acc/s nên không phải nút thắt. Nút thắt là **sidecar ký** (~12 chữ ký/giây)
và **giới hạn tần suất của TikTok theo IP**. Tăng luồng từ 20 lên 50 thường
**không nhanh thêm** — chỉ làm hàng đợi dài ra. Xem dải màu cam trong ô đồng hồ để
biết sidecar có đang nghẽn không.

Vì vậy: **càng nhiều tài khoản, càng cần proxy xoay IP** (tab Cài đặt). Không có
proxy, TikTok sẽ khóa IP sau khoảng vài chục request.

---

## ⚠️ Cần sidecar ký request

TikTok bắt buộc mọi request API có chữ ký `X-Bogus` / `X-Gnarly`. App này **không tự
reverse-engineer** mà gọi một tiến trình Node dùng SDK thật, chạy cục bộ ở
`http://127.0.0.1:8080`:

```bash
git clone https://github.com/carcabot/tiktok-signature.git
cd tiktok-signature
npm install
npx puppeteer browsers install chrome
npm start
```

Hoặc chạy `signer.bat` (Windows) / `./signer.sh` (macOS, Linux) — script tự làm hết
các bước trên. **Phải giữ cửa sổ terminal đó mở.**
```

App sẽ tự báo trạng thái sidecar ở thanh dưới cùng. Nếu hiện `KHÔNG kết nối`, hãy chạy
lệnh trên rồi bấm lại vào cửa sổ.

---

## Bố cục 4 tab

| Tab | Chứa năng |
|---|---|
| **Quản lý** | Thanh công cụ + ô tìm kiếm + bảng 2 cột A/B + thanh phân trang. Bảng chiếm **toàn bộ bề ngang**. |
| **Tác vụ** | Chọn chế độ, nhập `cid` / `aweme_id` / URL, số luồng, trễ, thử lại, backend. |
| **Chi tiết** | Thẻ bài viết đang nhắm tới, thẻ tài khoản đang chọn, thẻ tổng quan, nhật ký. |
| **Cài đặt** | Proxy theo tài khoản, cổng VPN Express, proxy hệ thống, tham số chạy. |

Nút **☰ Nhật ký** trên thanh công cụ nhảy thẳng sang tab Chi tiết. Tiêu đề tab Chi
tiết hiện số lỗi (`Chi tiết (1 lỗi)`) nên thấy ngay mà không cần mở.

## Quản lý danh sách lớn

Bảng ở tab **Quản lý** xử lý được danh sách hàng chục nghìn tài khoản:

| Tính năng | Cách dùng |
|---|---|
| **Tìm kiếm** | Gõ vào ô trên bảng. Khớp `username`, `email`, `user id`, `proxy`, trạng thái, kết quả. Nhiều từ phải khớp **tất cả** (`user00001 hotmail` → 1 dòng). Không phân biệt hoa thường. `Ctrl+F` để nhảy vào ô, `Esc` để xoá. |
| **Lọc nhanh** | Combo *Lọc*: còn phiên / thiếu phiên / đã tick / chưa tick / đã gán proxy / thành công / bị lỗi. |
| **Sắp xếp** | Bấm vào tiêu đề cột *A* (số thứ tự) hoặc *B* (trạng thái). Mũi tên hiện cột đang sắp. |
| **Phân trang** | 25 / 50 / 100 / 250 / 500 / 1000 / 5000 / Tất cả. Số thứ tự liên tục qua các trang. |
| **Tick hàng loạt** | *Tick tất cả* / *Bỏ tick* = toàn bộ danh sách. *Trang này ±* = chỉ trang đang xem. ***Tick kết quả lọc*** = mọi tài khoản đang khớp bộ lọc — dùng cái này thay vì lần lượt tick từng trang. |

Số thứ tự tính trên tập đang lọc, nên khi lọc "Thiếu phiên" thì cột STT đánh lại từ 1
trong nhóm đó. Nút **CHẠY** luôn dùng **mọi tài khoản đã tick**, không bị giới hạn theo
bộ lọc hay trang đang xem.

Đã đo trên máy dev: nạp 5 000 tài khoản 18 ms, lọc 9 ms, đổi trang < 1 ms.

## Tab "Cài đặt" — proxy

Mở tab **Cài đặt** để cấu hình proxy cho từng account.

### Nhập danh sách proxy

Dán vào ô bên trái, 1 dòng = 1 proxy:

```
1.2.3.4:8080
1.2.3.4:8080:userA:passA
userB:passB@5.6.7.8:1080
socks5://9.9.9.9:1080
# dòng bắt đầu bằng # sẽ bị bỏ qua
```

Bấm **Lưu & phân phối**. Mỗi account được gán 1 proxy, hiện ngay trên **cột A** của tab
Tài khoản (dạng `🌐 1.2.3.4:8080`). Bảng bên dưới cho biết IP thoát, quốc gia, độ trễ
và số account đang dùng — bấm **Kiểm tra toàn bộ proxy** để kiểm tra song song.

### Cổng VPN Express

Thay vì mua N địa chỉ IP, VPN Express cho một cổng duy nhất. IP thật nằm trong
**username**, đổi theo mã `session`:

```
http://{user}-country-{country}-session-{session}:{pass}@{host}:{port}
```

Điền Username/Password/Host/Cổng/Mã nước ở khung bên phải, tích *Dùng chế độ cổng*,
rồi **Lưu & phân phối**. Mỗi account tự động được cấp một `session` riêng — 500 account
vẫn chỉ cần 1 cấu hình proxy, và mỗi account giữ IP ổn định giữa các lần chạy.

Khi một account bị chặn IP, app tự cấp session mới cho nó (nếu bật *Tự đổi proxy khi bị
chặn IP*).

### Proxy hệ thống

Khi một tài khoản **chưa được gán proxy nào**, app dùng proxy hệ thống của máy thay
vì đi thẳng ra IP thật. Tích ô *Khi tài khoản chưa được gán proxy nào…* rồi bấm
**Phát hiện** — app đọc theo đúng thứ tự:

1. Windows: registry WinINET (cùng nguồn với trình duyệt)
2. macOS: `scutil --proxy`
3. Linux/GNOME: `gsettings`
4. Biến môi trường `HTTPS_PROXY` / `ALL_PROXY` / `HTTP_PROXY`

Nếu cả 4 đều trống thì báo rõ và chạy bằng IP máy. Có thể sửa tay URL trong ô.

### Tự động đổi proxy

Ở tab Tài khoản có ô **Dùng proxy gán ở tab Cài đặt**. Khi TikTok trả mã lỗi liên
quan IP (`8`, `10202`, `10221`, `10222`, `350002`), app đổi sang proxy kế tiếp rồi thử lại
— tối đa số lần bạn đặt ở *Thử lại*.

Cấu hình (kể cả mật khẩu proxy) tự lưu khi đóng app.

## Tốc độ

Tốc độ scale gần tuyến tính theo số luồng cho tới khi chạm trần của sidecar (~12 chữ ký/giây).
Với mỗi account 2 chữ ký:

| Số account | Thời gian ước tính |
|---|---|
| 50 | ~8 giây |
| 500 | ~85 giây |
| 5000 | ~14 phút |

Muốn nhanh hơn: tắt *Xác minh số like*, bỏ bước kiểm tra đăng nhập, hoặc chạy
2–3 sidecar ở các cổng khác nhau.

Nút thắt thật sự là **IP**, không phải thread — nhiều account trên một IP dễ bị TikTok
phát hiện. Xem tab Cài đặt.

## Tham số request

Request thả tim gửi tới `POST /api/comment/digg/` với 27 tham số fingerprint. App tự
lấy từ cookie và suy ra từ User-Agent của sidecar: ngôn ngữ theo `store-country-code`,
`verifyFp` từ cookie `s_v_web_id`, `history_len=8`, header `tt-csrf-token`, `Referer`
trang chủ theo locale.

Chạy `python test_digg_url.py` để so toàn bộ tham số với request thật của bạn.

---

## Cấu trúc

```
main.py                    điểm khởi chạy
core/
  parser.py                đọc file cookie, lấy aweme_id từ URL
  models.py                Account + model 2 cột A/B + tìm kiếm/lọc/sắp xếp/phân trang
  runner.py                QThreadPool, QRunnable, tín hiệu thread-safe
  signer.py                client của sidecar ký
  tiktok.py                client API (curl_cffi giả TLS Chrome)
  config.py                RunConfig + 4 chế độ tác vụ
  proxy.py                 parse / phân phối / xoay vòng / kiểm tra proxy / proxy hệ thống
  settings.py              lưu cấu hình JSON
  gui_bridge.py            đưa callback từ thread nền về GUI thread
  inflight.py              đếm request đang treo → nguồn cho đồng hồ "đang chờ"
  backends/
    base.py                interface + Progress/StopFlag
    http_backend.py        tác vụ thật
    mock_backend.py        giả lập để test
ui/
  main_window.py           tab Quản lý + Tác vụ
  settings_tab.py          tab Cài đặt (proxy, cổng VPN Express, cấu hình)
  detail_panel.py          thẻ bài viết + thẻ tài khoản
  delegates.py             vẽ 2 cột + ô tick
  style.py                 style chung (màu, bảng, nút)
smoke_test.py              test đa luồng không cần GUI
test_inflight.py           test đồng hồ "đang chờ" + bộ đếm liên mạch (30 kiểm tra)
test_search.py             test tìm kiếm/lọc/sắp xếp/phân trang (37 kiểm tra)
test_paging.py             test phân trang (23 kiểm tra)
test_proxy.py              test lớp proxy (25 kiểm tra)
test_digg_url.py           so 27 tham số với request thật
cokie.tik.txt              dữ liệu của bạn (đừng commit)
```

---

## Quy tắc luồng (không sửa được)

Worker thread **không bao giờ** chạm widget hay model — chỉ `emit` signal.
`MainWindow` là nơi duy nhất gọi `model.update_row()`, và cập nhật theo `account.id`
chứ không theo chỉ số dòng.

---

## Lưu ý

File cookie tương đương mật khẩu — đừng commit lên git, đừng chia sẻ. File
`settings.json` cũng chứa mật khẩu proxy ở dạng plaintext, coi nó cùng mức nhạy cảm.
Tự động hoá trên TikTok vi phạm Điều khoản dịch vụ và có thể khiến tài khoản bị khoá.
