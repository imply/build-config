# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Copies the given "win tool" (which the toolchain uses to wrap compiler
# invocations) and the environment blocks for the 32-bit and 64-bit builds on
# Windows to the build directory.
#
# The arguments are the visual studio install location and the location of the
# win tool. The script assumes that the root build directory is the current dir
# and the files will be written to the current directory.

import errno
import json
import os
import re
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))
import gn_helpers

SCRIPT_DIR = os.path.dirname(__file__)

def _ExtractImportantEnvironment(output_of_set):
  """Extracts environment variables required for the toolchain to run from
  a textual dump output by the cmd.exe 'set' command."""
  envvars_to_save = (
      'include',
      'lib',
      'libpath',
      'path',
      'pathext',
      'systemroot',
      'temp',
      'tmp',
      )
  env = {}
  # This occasionally happens and leads to misleading SYSTEMROOT error messages
  # if not caught here.
  if output_of_set.count('=') == 0:
    raise Exception('Invalid output_of_set. Value is:\n%s' % output_of_set)
  for line in output_of_set.splitlines():
    for envvar in envvars_to_save:
      if re.match(envvar + '=', line.lower()):
        var, setting = line.split('=', 1)
        if envvar == 'path':
          # Our own rules and actions in Chromium rely on python being in the
          # path. Add the path to this python here so that if it's not in the
          # path when ninja is run later, python will still be found.
          setting = os.path.dirname(sys.executable) + os.pathsep + setting
        env[var.upper()] = setting
        break
  if sys.platform in ('win32', 'cygwin'):
    for required in ('SYSTEMROOT', 'TEMP', 'TMP'):
      if required not in env:
        raise Exception('Environment variable "%s" '
                        'required to be set to valid path' % required)
  return env


def _DetectVisualStudioPath():
  """Return path to the GYP_MSVS_VERSION of Visual Studio.
  """
  import vs_toolchain
  return vs_toolchain.DetectVisualStudioPath()


def _LoadEnvFromBat(args):
  """Given a bat command, runs it and returns env vars set by it."""
  args = args[:]
  args.extend(('&&', 'set'))
  popen = subprocess.Popen(
      args, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  variables, _ = popen.communicate()
  if popen.returncode != 0:
    raise Exception('"%s" failed with error %d' % (args, popen.returncode))
  return variables


def _LoadToolchainEnv(cpu, sdk_dir):
  """Returns a dictionary with environment variables that must be set while
  running binaries from the toolchain (e.g. INCLUDE and PATH for cl.exe)."""
  # Check if we are running in the SDK command line environment and use
  # the setup script from the SDK if so. |cpu| should be either
  # 'x86' or 'x64'.
  assert cpu in ('x86', 'x64')
  # We only support x64-hosted tools.
  script_path = os.path.normpath(os.path.join(
                                     _DetectVisualStudioPath(),
                                     'VC/vcvarsall.bat'))
  if not os.path.exists(script_path):
    raise Exception('%s is missing - make sure VC++ tools are installed.' %
                    script_path)
  args = [script_path, 'amd64_x86' if cpu == 'x86' else 'amd64']
  variables = _LoadEnvFromBat(args)
  return _ExtractImportantEnvironment(variables)


def _FormatAsEnvironmentBlock(envvar_dict):
  """Format as an 'environment block' directly suitable for CreateProcess.
  Briefly this is a list of key=value\0, terminated by an additional \0. See
  CreateProcess documentation for more details."""
  block = ''
  nul = '\0'
  for key, value in envvar_dict.iteritems():
    block += key + '=' + value + nul
  block += nul
  return block


def main():
  if len(sys.argv) != 6:
    print('Usage setup_toolchain.py '
          '<visual studio path> <win sdk path> '
          '<runtime dirs> <target_cpu> <include prefix>')
    sys.exit(2)
  win_sdk_path = sys.argv[2]
  runtime_dirs = sys.argv[3]
  target_cpu = sys.argv[4]
  include_prefix = sys.argv[5]

  cpus = ('x86', 'x64')
  assert target_cpu in cpus
  vc_bin_dir = ''
  include = ''

  # TODO(scottmg|goma): Do we need an equivalent of
  # ninja_use_custom_environment_files?

  for cpu in cpus:
    # Extract environment variables for subprocesses.
    env = _LoadToolchainEnv(cpu, win_sdk_path)
    env['PATH'] = runtime_dirs + os.pathsep + env['PATH']

    if cpu == target_cpu:
      for path in env['PATH'].split(os.pathsep):
        if os.path.exists(os.path.join(path, 'cl.exe')):
          vc_bin_dir = os.path.realpath(path)
          break
      # The separator for INCLUDE here must match the one used in
      # _LoadToolchainEnv() above.
      include = [include_prefix + p for p in env['INCLUDE'].split(';') if p]
      include = ' '.join(['"' + i.replace('"', r'\"') + '"' for i in include])

    env_block = _FormatAsEnvironmentBlock(env)
    with open('environment.' + cpu, 'wb') as f:
      f.write(env_block)

    # Create a store app version of the environment.
    if 'LIB' in env:
      env['LIB']     = env['LIB']    .replace(r'\VC\LIB', r'\VC\LIB\STORE')
    if 'LIBPATH' in env:
      env['LIBPATH'] = env['LIBPATH'].replace(r'\VC\LIB', r'\VC\LIB\STORE')
    env_block = _FormatAsEnvironmentBlock(env)
    with open('environment.winrt_' + cpu, 'wb') as f:
      f.write(env_block)

  assert vc_bin_dir
  print 'vc_bin_dir = ' + gn_helpers.ToGNString(vc_bin_dir)
  assert include
  print 'include_flags = ' + gn_helpers.ToGNString(include)

if __name__ == '__main__':
  main()
