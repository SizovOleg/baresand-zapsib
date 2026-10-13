"""
cpu_limit.py - не занимать весь процессор (просьба владельца 2026-09-27: «проц не вешаем на 100 %»).

apply(): пониженный приоритет процесса (BELOW_NORMAL; дочерние процессы Windows его наследуют) и лимит потоков
OpenMP / BLAS (бустинг sklearn, numpy) до четверти ядер. Вызывать в начале скрипта до тяжёлых вычислений.
"""
import os

CPU_THREADS = 4
CPU_AFFINITY = [20, 21, 22, 23]  # User: CORONA4 + imagery4, 2026-09-27
RENDER_WORKERS = 4


def apply_heavy(reserve: int = 2) -> int:
    """Режим, разрешённый владельцем 2026-10-04 для кадастрового оверлея: все ядра, кроме reserve последних,
    пониженный приоритет; возвращает число рабочих процессов. Дочерние процессы Windows наследуют маску и приоритет."""
    n = max(1, (os.cpu_count() or 4) - reserve)
    for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[k] = '1'
    try:
        import psutil
        p = psutil.Process()
        if os.name == 'nt':
            p.cpu_affinity(list(range(n)))
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)
    except Exception as e:
        print(f'cpu_limit: приоритет не понижен: {e!r}', flush=True)
    return n


def apply_cores(n: int = 12) -> int:
    """Режим, разрешённый владельцем 2026-10-06 для отрисовки снимков (137): n ядер (10..10+n-1, без 0-9 и двух
    последних), пониженный приоритет, по одному потоку BLAS на процесс; возвращает n. Дочерние процессы наследуют."""
    total = os.cpu_count() or 4
    cores = [c for c in range(10, 10 + n) if c < total - 2] or list(range(max(1, total - 2)))
    for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[k] = '1'
    try:
        import psutil
        p = psutil.Process()
        if os.name == 'nt':
            p.cpu_affinity(cores)
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)
    except Exception as e:
        print(f'cpu_limit: приоритет не понижен: {e!r}', flush=True)
    return len(cores)


def apply() -> int:
    for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[k] = str(CPU_THREADS)
    try:
        import psutil
        p = psutil.Process()
        if os.name == "nt":
            p.cpu_affinity(CPU_AFFINITY)
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)
    except Exception as e:
        print(f'cpu_limit: приоритет не понижен: {e!r}', flush=True)
    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(limits=CPU_THREADS)
    except Exception as e:
        print(f'cpu_limit: лимит потоков не задан: {e!r}', flush=True)
    return CPU_THREADS
