"""One uploader per local database, including multiple desktop instances."""
from contextlib import contextmanager
from pathlib import Path
import os

@contextmanager
def uploader_lock(db_path):
    path=Path(str(db_path)+".sync.lock")
    stream=open(path,"a+b")
    locked=False
    try:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b"0");stream.flush()
        stream.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError as exc:
            raise RuntimeError("另一个同步任务正在运行，请等待完成") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_UN)
        stream.close()
