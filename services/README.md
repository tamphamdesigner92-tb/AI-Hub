# Chạy nền

## Dashboard — nên bật

```powershell
.\services\dashboard-autostart.ps1 -Install
```

Đăng ký một Scheduled Task chạy lúc đăng nhập, ẩn hoàn toàn, không cần quyền
admin. Sau đó `http://127.0.0.1:7860` luôn vào được.

Server chỉ tốn ~20 MB RAM và không nạp model nào — nó chỉ đọc đĩa và hỏi Ollama.
Vì vậy để thường trú là hợp lý.

Gỡ: `.\services\dashboard-autostart.ps1 -Uninstall` · Xem trạng thái: `-Status`

## Ollama — cố tình KHÔNG có autostart

Bản macOS có một file template launchd cho Ollama và khuyến nghị không cài. Trên
Windows lý do còn mạnh hơn:

1. **Trình cài Ollama đã tự thêm mục khởi động của nó.** Thêm một cái nữa thì hai
   tiến trình tranh cổng 11434, cái thứ hai chết lặng lẽ.
2. **Server thường trú giữ RAM.** `aihub serve` bật khi cần, `OLLAMA_KEEP_ALIVE=5m`
   nhả model sau 5 phút rảnh.
3. **`ollama serve` prune blob vô chủ mỗi lần khởi động.** Bạn muốn kiểm soát thời
   điểm đó, nhất là ngay sau khi `aihub migrate` vừa dời kho.

Muốn Ollama luôn bật thì dùng chính mục khởi động sẵn có của nó, và đảm bảo biến
`OLLAMA_MODELS` đã được ghi ở mức người dùng để nó tìm đúng kho:

```powershell
.\scripts\migrate.ps1 -SetUserEnv
```

Kiểm tra biến đã vào chưa: `aihub doctor` — dòng *biến người dùng OLLAMA_MODELS*.
