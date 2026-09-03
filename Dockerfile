FROM parsafadaeei/telegram-bot:latest

COPY requirements.txt /tmp/requirements.txt

RUN apk add --no-cache aria2 curl unzip nodejs ffmpeg && \
    curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip && \
    unzip rclone-current-linux-amd64.zip && \
    cp rclone-*-linux-amd64/rclone /usr/bin/rclone && \
    chmod +x /usr/bin/rclone && \
    rm -rf rclone-* && \
    pip install --no-cache-dir -r /tmp/requirements.txt --break-system-packages

ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app/
RUN chmod +x /app/start_railway.sh
RUN mkdir -p /root/.config/yt-dlp && echo '--js-runtimes node' > /root/.config/yt-dlp/config
CMD ["/app/start_railway.sh"]
