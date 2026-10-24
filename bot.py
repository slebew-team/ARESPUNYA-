import asyncio
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageOps
from telegram import InputMediaPhoto
from telegram.ext import Application, CommandHandler

Image.MAX_IMAGE_PIXELS = 25_000_000
busy = set()


def prepare(path):
    with zipfile.ZipFile(path) as archive:
        entries = [
            item for item in archive.infolist()
            if not item.is_dir()
            and item.filename.lower().endswith((".jpg", ".jpeg"))
            and not item.filename.startswith("__MACOSX/")
        ]
        if not entries or len(entries) > 200:
            raise ValueError("ZIP harus berisi 1–200 JPG/JPEG.")
        if sum(x.file_size for x in archive.infolist()) > 200 * 1024**2:
            raise ValueError("Isi ZIP maksimal 200 MB.")

        def order(item):
            return [
                int(part) if part.isdigit() else part.lower()
                for part in re.split(r"(\d+)", item.filename)
            ]

        photos = []
        for item in sorted(entries, key=order):
            with archive.open(item) as source:
                with Image.open(source) as image:
                    if image.format != "JPEG":
                        raise ValueError("Ada file yang bukan JPEG asli.")
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((2560, 2560))
                    if max(image.size) / min(image.size) > 20:
                        raise ValueError("Gambar terlalu panjang.")
                    output = io.BytesIO()
                    image.save(output, "JPEG", quality=90)
                    photos.append(output.getvalue())
        return photos


async def start(update, context):
    await update.effective_message.reply_text(
        "Kirim ZIP berisi JPG/JPEG, lalu balas ZIP dengan "
        "/proses atau /proses@username_bot. Maksimal ZIP 20 MB."
    )


async def process(update, context):
    message = update.effective_message
    source = message.reply_to_message

    if not source or not source.document:
        await message.reply_text("Balas pesan ZIP dengan /proses.")
        return

    document = source.document
    if not (document.file_name or "").lower().endswith(".zip"):
        await message.reply_text("File harus berformat ZIP.")
        return
    if (document.file_size or 0) > 20 * 1024**2:
        await message.reply_text("Ukuran ZIP maksimal 20 MB.")
        return
    if message.chat_id in busy:
        await message.reply_text("Tunggu, ZIP sebelumnya masih diproses.")
        return

    busy.add(message.chat_id)
    sent = 0
    try:
        await message.reply_text("Sedang menyiapkan foto…")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.zip"
            remote = await document.get_file()
            await remote.download_to_drive(path)
            photos = await asyncio.to_thread(prepare, path)

        title = Path(document.file_name).stem[:200]
        total = (len(photos) + 9) // 10
        for offset in range(0, len(photos), 10):
            batch = photos[offset:offset + 10]
            caption = (
                f"{title}\nBagian {offset // 10 + 1}/{total}"
            )
            options = {
                "chat_id": message.chat_id,
                "message_thread_id": message.message_thread_id,
            }
            if len(batch) == 1:
                await context.bot.send_photo(
                    photo=batch[0], caption=caption, **options
                )
            else:
                media = [
                    InputMediaPhoto(
                        photo, caption=caption if index == 0 else None
                    )
                    for index, photo in enumerate(batch)
                ]
                await context.bot.send_media_group(media=media, **options)
            sent += len(batch)
            await asyncio.sleep(1)

        await message.reply_text(f"Selesai! {sent} foto terkirim.")
    except Exception:
        await message.reply_text(
            f"Proses gagal setelah {sent} foto terkirim. "
            "Pastikan ZIP tidak berpassword, berisi JPG valid, "
            "maksimal 200 gambar/200 MB setelah dibuka, dan bot "
            "boleh mengirim foto. Jika diulang, proses mulai dari awal."
        )
    finally:
        busy.discard(message.chat_id)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diatur.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("proses", process))
    app.run_polling()


if __name__ == "__main__":
    main()
