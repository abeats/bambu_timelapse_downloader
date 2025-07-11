import ftplib
import ssl
import os
import sys
import argparse
import configparser
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from tqdm import tqdm

app_name = __name__
version = '1.0.0.1'

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
elif __file__:
    application_path = os.path.dirname(__file__)


def setup_logging(log_root_directory=f'{application_path}/logs', logger_name=app_name,
                  log_file_max_byte_size=104857, log_file_max_backup=3,
                  log_default_level=logging.DEBUG, console_level=logging.INFO, logfile_level=logging.DEBUG):
    """
    Sets up logging to console and rotating log file.
    """
    today = datetime.today()
    year = today.strftime('%Y')
    month = today.strftime('%m')
    log_name_ = logger_name.rstrip('.log') + f'_{os.getlogin()}' + '.log'
    log_name = today.strftime(f'%Y%m%d_{log_name_}')

    log_format_console = "[%(asctime)s] %(levelname)s %(message)s"  # <- Simplified console format
    log_format_file = "[%(asctime)s:%(filename)s:%(lineno)s:%(name)s.%(funcName)s()] %(levelname)s %(message)s"
    log_date_format = '%Y-%m-%d %H:%M:%S'

    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    log_directory = f'{log_root_directory}/{year}/{month}'

    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    log_file_path = f'{log_directory}/{log_name}'
    log_file_handler = RotatingFileHandler(filename=log_file_path, mode='a',
                                           maxBytes=log_file_max_byte_size,
                                           backupCount=log_file_max_backup,
                                           delay=False,
                                           encoding='utf8')

    log_console_handler = logging.StreamHandler()
    log_console_handler.setLevel(console_level)
    log_console_handler.setFormatter(logging.Formatter(log_format_console, datefmt=log_date_format))

    log_file_handler.setLevel(logfile_level)
    log_file_handler.setFormatter(logging.Formatter(log_format_file, datefmt=log_date_format))

    logger.setLevel(log_default_level)
    logger.addHandler(log_console_handler)
    logger.addHandler(log_file_handler)
    return logger


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """FTP_TLS subclass that automatically wraps sockets in SSL to support implicit FTPS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value


def ftp_download(args):
    try:
        if not os.path.exists(args.download_dir):
            os.makedirs(args.download_dir)

        downloaded_files = [f for f in os.listdir(args.download_dir) if f.endswith('.avi')]

        logger.info(f'Connecting to printer {args.user}@{args.ip}:{args.port}')
        ftp_client = ImplicitFTP_TLS()
        ftp_client.connect(host=args.ip, port=990)
        ftp_client.login(user=args.user, passwd=args.password)
        ftp_client.prot_p()
        logger.info('Connected.')
    except Exception as e:
        logger.error(f'FTP connection failed, error: "{e}"')
        sys.exit(1)

    try:
        if args.ftp_timelapse_folder in ftp_client.nlst():
            ftp_client.cwd(args.ftp_timelapse_folder)
            try:
                logger.info('Looking for .avi files to download...')
                ftp_timelapse_files = [f for f in ftp_client.nlst() if f.endswith('.avi')]
                ftp_timelapse_files = [f for f in ftp_timelapse_files if f not in downloaded_files]

                total_files = len(ftp_timelapse_files)

                if total_files:
                    logger.info(f'Found {total_files} files for download.')
                    for index, f in enumerate(ftp_timelapse_files, start=1):
                        filesize = ftp_client.size(f)
                        filesize_mb = round(filesize / 1024 / 1024, 2)
                        download_file_path = f'{args.download_dir}/{f}'

                        if filesize == 0:
                            logger.info(f'Filesize of file {f} is 0, skipping file and continuing...')
                            continue
                        try:
                            logger.info(f'Starting download [{index}/{total_files}] "{f}" size: {filesize_mb} MB')
                            with open(download_file_path, 'wb') as fhandle, tqdm(
                                total=filesize,
                                unit='B',
                                unit_scale=True,
                                unit_divisor=1024,
                                desc=f"[{index}/{total_files}] {f}",
                                leave=True,
                                ncols=100
                            ) as pbar:
                                def callback(data):
                                    fhandle.write(data)
                                    pbar.update(len(data))

                                ftp_client.retrbinary(f'RETR {f}', callback)

                            if args.delete_files_from_sd_card_after_download:
                                try:
                                    ftp_client.delete(f)
                                except Exception as e:
                                    logger.error(f'Failed to delete file after download: {e}, continuing...')
                                    continue
                        except Exception as e:
                            if os.path.exists(download_file_path):
                                os.remove(download_file_path)
                            logger.error(f'Failed to download file {f}: {e}, continuing...')
                            continue
                else:
                    logger.info("No new .avi files to download.")
            except ftplib.error_perm as resp:
                if str(resp) == "550 No files found":
                    logger.error("No files in this directory")
                else:
                    raise
        else:
            logger.info(f'{args.ftp_timelapse_folder} not found on FTP server.')
            sys.exit(1)
    except Exception as e:
        logger.error(f'Program failed: {e}')
        sys.exit(1)


if __name__ == '__main__':
    logger = setup_logging()

    logger.info(f'Starting Bambu timelapse downloader v{version}')
    parser = argparse.ArgumentParser(description='Download Bambu timelapses from printer FTP server.')
    parser.add_argument('--ip', type=str)
    parser.add_argument('--port', type=int, default=990, required=False)
    parser.add_argument('--user', type=str, default='bblp', required=False)
    parser.add_argument('--password', type=str)
    parser.add_argument('--download_dir', type=str, default=f'{application_path}/timelapse', required=False)
    parser.add_argument('--ftp_timelapse_folder', type=str, default='timelapse', required=False)
    parser.add_argument('--delete_files_from_sd_card_after_download', '-d', action='store_true')
    parser.add_argument("-v", "--version", action="version", version=f'%(prog)s - Version {version}')
    args = parser.parse_args()

    ftp_download(args)