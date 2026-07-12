#![windows_subsystem = "windows"]

use std::env;
use std::os::windows::process::CommandExt;
use std::process::{Command, ExitCode, Stdio};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn main() -> ExitCode {
    let mut args = env::args_os();
    let _launcher = args.next();
    let Some(program) = args.next() else {
        eprintln!("usage: xinao-hidden-stdio.exe <program> [args...]");
        return ExitCode::from(64);
    };

    match Command::new(program)
        .args(args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .creation_flags(CREATE_NO_WINDOW)
        .status()
    {
        Ok(status) => ExitCode::from(status.code().unwrap_or(1) as u8),
        Err(error) => {
            eprintln!("xinao-hidden-stdio: {error}");
            ExitCode::from(1)
        }
    }
}
