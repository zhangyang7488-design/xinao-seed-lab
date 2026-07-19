#Requires -Version 5.1

$ErrorActionPreference = "Stop"

if (-not ("Xinao.Grok.WindowsPathNative" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Xinao.Grok {
    [StructLayout(LayoutKind.Sequential)]
    public struct ByHandleFileInformation {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    public static class WindowsPathNative {
        public const uint FILE_SHARE_READ = 0x00000001;
        public const uint FILE_SHARE_WRITE = 0x00000002;
        public const uint FILE_SHARE_DELETE = 0x00000004;
        public const uint OPEN_EXISTING = 3;
        public const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern SafeFileHandle CreateFileW(
            string fileName,
            uint desiredAccess,
            uint shareMode,
            IntPtr securityAttributes,
            uint creationDisposition,
            uint flagsAndAttributes,
            IntPtr templateFile);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern uint GetFinalPathNameByHandleW(
            SafeFileHandle file,
            System.Text.StringBuilder path,
            uint pathLength,
            uint flags);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool GetFileInformationByHandle(
            SafeFileHandle file,
            out ByHandleFileInformation information);
    }
}
"@
}

function Open-GrokDirectoryIdentityLease {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "PATH_IDENTITY_OPEN_FAILED: empty path"
    }
    $requested = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $requested -PathType Container)) {
        throw "PATH_IDENTITY_OPEN_FAILED: $requested"
    }
    $share = [Xinao.Grok.WindowsPathNative]::FILE_SHARE_READ -bor
        [Xinao.Grok.WindowsPathNative]::FILE_SHARE_WRITE -bor
        [Xinao.Grok.WindowsPathNative]::FILE_SHARE_DELETE
    $handle = [Xinao.Grok.WindowsPathNative]::CreateFileW(
        $requested,
        0,
        $share,
        [IntPtr]::Zero,
        [Xinao.Grok.WindowsPathNative]::OPEN_EXISTING,
        [Xinao.Grok.WindowsPathNative]::FILE_FLAG_BACKUP_SEMANTICS,
        [IntPtr]::Zero
    )
    if ($null -eq $handle -or $handle.IsInvalid) {
        $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        if ($null -ne $handle) { $handle.Dispose() }
        throw "PATH_IDENTITY_OPEN_FAILED: $requested win32=$code"
    }

    try {
        $info = New-Object Xinao.Grok.ByHandleFileInformation
        if (-not [Xinao.Grok.WindowsPathNative]::GetFileInformationByHandle($handle, [ref]$info)) {
            $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw "PATH_IDENTITY_INFO_FAILED: $requested win32=$code"
        }
        $capacity = 1024
        while ($true) {
            $builder = [Text.StringBuilder]::new($capacity)
            $length = [Xinao.Grok.WindowsPathNative]::GetFinalPathNameByHandleW(
                $handle, $builder, [uint32]$builder.Capacity, 0
            )
            if ($length -eq 0) {
                $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                throw "PATH_IDENTITY_FINAL_PATH_FAILED: $requested win32=$code"
            }
            if ($length -lt $builder.Capacity) {
                $finalPath = $builder.ToString()
                break
            }
            $capacity = [int]$length + 1
        }
        $fileIndex = ([uint64]$info.FileIndexHigh -shl 32) -bor [uint64]$info.FileIndexLow
        return [pscustomobject]@{
            requested_path = $requested
            final_path = $finalPath
            volume_serial_number = [uint32]$info.VolumeSerialNumber
            file_index = $fileIndex
            object_id = ('{0:x8}:{1:x16}' -f [uint32]$info.VolumeSerialNumber, $fileIndex)
            opened_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            handle = $handle
            disposed = $false
        }
    }
    catch {
        $handle.Dispose()
        throw
    }
}

function Close-GrokDirectoryIdentityLease {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Lease)
    if ($Lease.disposed -eq $true) { return }
    if ($null -ne $Lease.handle) { $Lease.handle.Dispose() }
    $Lease.disposed = $true
}

function Get-GrokDirectoryIdentitySnapshot {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)
    $lease = Open-GrokDirectoryIdentityLease -Path $Path
    try {
        return [pscustomobject]@{
            requested_path = $lease.requested_path
            final_path = $lease.final_path
            volume_serial_number = $lease.volume_serial_number
            file_index = $lease.file_index
            object_id = $lease.object_id
        }
    }
    finally {
        Close-GrokDirectoryIdentityLease -Lease $lease
    }
}

function Test-GrokDirectoryObjectIdentityEqual {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Left,
        [Parameter(Mandatory = $true)]$Right
    )
    return (
        [uint32]$Left.volume_serial_number -eq [uint32]$Right.volume_serial_number -and
        [uint64]$Left.file_index -eq [uint64]$Right.file_index
    )
}

function Assert-GrokDirectoryIdentityLeaseStable {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Lease)
    if ($Lease.disposed -eq $true) { throw "PATH_IDENTITY_LEASE_DISPOSED" }
    $fresh = Open-GrokDirectoryIdentityLease -Path $Lease.requested_path
    try {
        if (
            -not (Test-GrokDirectoryObjectIdentityEqual -Left $Lease -Right $fresh) -or
            -not [string]::Equals(
                [string]$Lease.final_path,
                [string]$fresh.final_path,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "PATH_IDENTITY_JUNCTION_RETARGET: $($Lease.requested_path)"
        }
        return $true
    }
    finally {
        Close-GrokDirectoryIdentityLease -Lease $fresh
    }
}
