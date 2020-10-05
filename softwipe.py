#!/usr/bin/env python3
"""
The main module of softwipe. Here, command line arguments get parsed and the pipeline gets started.
"""

import argparse
import os
import re
import sys
from multiprocessing.pool import ThreadPool

import automatic_tool_installation
import compile_phase
import execution_phase
import scoring
import static_analysis_phase
import strings
import util


def parse_arguments():
    """
    Parse command line arguments.
    :return: The "args" Namespace that contains the command line arguments specified by the user.
    """
    # Preparser, used for the command, execute, and compiler options file helps. Without the preparser, one would get
    # an error because 'programdir' is a required argument but is missing. With the preparser, the help can be
    # printed anyway.
    preparser = argparse.ArgumentParser(add_help=False)
    preparser.add_argument('--commandfilehelp', default=False, action='store_true')
    preparser.add_argument('--executefilehelp', default=False, action='store_true')
    preparser.add_argument('--compileroptionsfilehelp', default=False, action='store_true')
    preargs, _ = preparser.parse_known_args()

    # All helps can be printed at once
    if preargs.executefilehelp:
        print(strings.EXECUTE_FILE_HELP)
    if preargs.commandfilehelp:
        print(strings.COMMAND_FILE_HELP)
    if preargs.compileroptionsfilehelp:
        print(strings.COMPILER_OPTIONS_FILE_HELP)
    if preargs.executefilehelp or preargs.commandfilehelp or preargs.compileroptionsfilehelp:
        # Exit if either one, any of the, or all helps have been printed
        sys.exit(0)

    # Main parser
    parser = argparse.ArgumentParser(description='Check the software quality of a C/C++ program\n\n'
                                                 'Important arguments you probably want to use:\n'
                                                 '  -c/-C to tell me whether your program is C or C++\n'
                                                 '  -M/-m/-l to tell me how to build your program (cmake, make, '
                                                 'raw clang)\n'
                                                 '  -e to specify a file that tells me how to execute your program\n'
                                                 'Example command line for a CMake-based C++ program:\n'
                                                 './softwipe.py -CM path/to/program -e path/to/executefile\n',
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('programdir', help="the root directory of your target program")

    c = parser.add_mutually_exclusive_group()
    c.add_argument('-c', '--cc', action='store_true', help='use C. This is the default option')
    c.add_argument('-C', '--cpp', action='store_true', help='use C++')

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('-M', '--cmake', action='store_true', help='compile the program using cmake. This is the default '
                                                                 'option')
    mode.add_argument('-m', '--make', action='store_true', help='compile the program using make. Note that this '
                                                                'option requires a "standard" style makefile that '
                                                                'uses common variable names like ${CC}, ${CFLAGS}, '
                                                                '${LDFLAGS} etc. to work properly')
    mode.add_argument('-l', '--clang', nargs='+', metavar='target', help='compile the program using the clang/clang++ '
                                                                         'compiler. This option takes as arguments the'
                                                                         ' files to compile')

    parser.add_argument('-e', '--executefile', nargs=1, help='path to an "execute file" which contains a command line '
                                                             'that executes your program')
    parser.add_argument('--executefilehelp', action='store_true', help='print detailled information about how the '
                                                                       'execute file works and exit')

    parser.add_argument('-f', '--commandfile', nargs=1, help='path to a "command file" which can be used to provide '
                                                             'commands that should be executed for building a '
                                                             'make-based project')
    parser.add_argument('--commandfilehelp', action='store_true', help='print detailed information about how the '
                                                                       'command file works and exit')

    parser.add_argument('-o', '--compileroptionsfile', nargs=1, help='path to a "compiler options file" which '
                                                                     'contains one line with options that must be '
                                                                     'passed to the compiler for correct compilation '
                                                                     'of your program')
    parser.add_argument('--compileroptionsfilehelp', action='store_true', help='print detailed information about how '
                                                                               'the compiler options file works and '
                                                                               'exit')

    parser.add_argument('-x', '--exclude', nargs=1, help='a comma separated lst of files and directories that should '
                                                         'be excluded from being analyzed by this program. If you '
                                                         'specify relative paths, they should be relative to the '
                                                         'directory you are running softwipe from')

    parser.add_argument('-p', '--path', nargs=1, help='a comma separated lst of paths that should be added to the '
                                                      'PATH environment variable. Use this if you have a dependency '
                                                      'installed but not accessible via your default PATH')

    parser.add_argument('--no-execution', action='store_true', help='Do not execute your program. This skips the '
                                                                    'clang sanitizer check')

    parser.add_argument('-a', '--custom-assert', nargs=1, help='a comma separated lst of custom assertions that '
                                                               'might be used in the code. Can be used to correct '
                                                               'your assertion score if you only/mostly use custom '
                                                               'assertion functions rather than raw C ones')

    parser.add_argument('--allow-running-as-root', action='store_true', help='Do not print a warning if the user is '
                                                                             'root')

    parser.add_argument('--add-badge', nargs=1)

    parser.add_argument('--exclude-assertions', action='store_true', help='Excludes the counting of assertions')
    parser.add_argument('--exclude-infer', action='store_true', help='Excludes Infer from the analysis')
    parser.add_argument('--exclude-compilation', action='store_true', help='Excludes the compilation of the program from the analysis')
    parser.add_argument('--exclude-lizard', action='store_true', help='Excludes Lizard from the analysis')
    parser.add_argument('--exclude-cppcheck', action='store_true', help='Excludes Cppcheck from the analysis')
    parser.add_argument('--exclude-kwstyle', action='store_true', help='Excludes KWStyle from the analysis')
    parser.add_argument('--exclude-clang-tidy', action='store_true', help='Excludes Clang-Tidy from the analysis')

    args = parser.parse_args()
    return args


def add_to_path_variable(paths):
    """
    Add paths to the system PATH environment variable.
    :param paths: A comma separated lst of paths to add.
    """
    path_list = []
    for path in paths.split(','):
        path_list.append(path)

    for path in path_list:
        os.environ['PATH'] += os.pathsep + path


def add_kwstyle_to_path_variable():
    """
    Adjusts the PATH variable by adding KWStyle to the PATH if it is contained in the softwipe directory (which it is
    if the user did the auto-installation of it).
    """
    kwstyle_dir = os.path.join(util.get_softwipe_directory(), 'KWStyle')
    if os.path.isdir(kwstyle_dir):
        add_to_path_variable(os.path.join(kwstyle_dir, strings.SOFTWIPE_BUILD_DIR_NAME))


def add_user_paths_to_path_variable(args):
    """
    Adjusts the PATH variable if necessary by adding user specified paths (if any were specified) to the PATH.
    :param args: The "args" Namespace as returned from parse_arguments().
    """
    user_paths = args.path[0] if args.path else None
    if user_paths:
        add_to_path_variable(user_paths)


def warn_if_user_is_root():
    """
    Check if the user is root, and print a warning if he is.
    """
    if os.geteuid() == 0:  # if user is root
        print(strings.USER_IS_ROOT_WARNING)
        while True:
            user_in = input('>>> ')
            if user_in in ('Y', 'Yes'):
                print("Okay, running as root now!")
                break
            elif user_in in ('n', 'no'):
                sys.exit(1)
            else:
                print('Please answer with "Y" (Yes) or "n" (no)!')


def compile_program(args, lines_of_code, cpp, compiler_flags, excluded_paths):
    """
    Run the automatic compilation of the target project.
    :param args: The "args" Namespace as returned from parse_arguments().
    :param lines_of_code: The lines of pure code count.
    :param cpp: Whether C++ is used or not. True if C++, False if C.
    :param compiler_flags: The flags to be used for compilation. Typically, these should be strings.COMPILE_FLAGS or,
    if no_execution, strings.COMPILER_WARNING_FLAGS.
    :param excluded_paths: A tupel containing the paths to be excluded.
    :return: The compiler score.
    """
    print(strings.RUN_COMPILER_HEADER)
    program_dir_abs = os.path.abspath(args.programdir)
    command_file = args.commandfile

    if args.make:
        if command_file:
            score = compile_phase.compile_program_make(program_dir_abs, lines_of_code, compiler_flags, excluded_paths,
                                                       make_command_file=command_file[0])
        else:
            score = compile_phase.compile_program_make(program_dir_abs, lines_of_code, compiler_flags, excluded_paths)
    elif args.clang:
        score = compile_phase.compile_program_clang(program_dir_abs, args.clang, lines_of_code, compiler_flags,
                                                    excluded_paths, cpp)
    else:
        if command_file:
            score = compile_phase.compile_program_cmake(program_dir_abs, lines_of_code, compiler_flags, excluded_paths,
                                                        make_command_file=command_file[0])
        else:
            score = compile_phase.compile_program_cmake(program_dir_abs, lines_of_code, compiler_flags, excluded_paths)

    return score


def compile_program_with_infer(args, excluded_paths):
    """
    Calls Infer compilation functions depending on the arguments received.
    :param args: softwipe arguments
    :param excluded_paths: paths to exclude from infer analysis
    :return: true - if compilation successful
             false - if compilation is not successful
    """
    program_dir_abs = os.path.abspath(args.programdir)

    if args.cmake:
        infer_compilation_status = compile_phase.compile_program_infer_cmake(program_dir_abs, excluded_paths)
    elif args.make:
        infer_compilation_status = compile_phase.compile_program_infer_make(program_dir_abs, excluded_paths)
    else:
        #TODO: allow clang compilation as well!!!
        print("Only make/cmake supported to analyze the program with Infer right now!")
        infer_compilation_status = False

    return infer_compilation_status


def execute_program(program_dir_abs, executefile, cmake, lines_of_code):
    """
    Execute the program and parse the output of the clang sanitizers.
    :param program_dir_abs: The absolute path to the root directory of the target program.
    :param executefile: The executefile that contains a command line for executing the program.
    :param cmake: Whether CMake has been used for compilation or not.
    :param lines_of_code: The lines of pure code count.
    :return The weighted sanitizer error count.
    """
    try:
        weighted_error_count = execution_phase.run_execution(program_dir_abs, executefile, cmake, lines_of_code)
    except execution_phase.ExecutionFailedException:
        print(strings.WARNING_PROGRAM_EXECUTION_SKIPPED)
        weighted_error_count = 0
    return weighted_error_count


def compile_and_execute_program_with_sanitizers(args, lines_of_code, program_dir_abs, cpp, excluded_paths,
                                                no_exec=False, exclude_infer=False):
    """
    Automatically compile and execute the program
    :param args: The "args" Namespace as returned from parse_arguments().
    :param lines_of_code: The lines of pure code count.
    :param program_dir_abs: The absolute path to the root directory of the target program.
    :param cpp: Whether C++ is used or not. True if C++, False if C.
    :param excluded_paths: A tupel containing the paths to be excluded.
    :param no_exec: If True, skip execution of the program.
    :param exclude_infer: If True, skip infer compilation.
    :return The compiler + sanitizer score.
    """
    compiler_flags = strings.COMPILER_WARNING_FLAGS if no_exec else strings.COMPILE_FLAGS
    if args.compileroptionsfile:
        options = open(args.compileroptionsfile[0], 'r').read().rstrip()
        compiler_flags += " " + options

    weighted_sum_of_compiler_warnings = compile_program(args, lines_of_code, cpp, compiler_flags, excluded_paths)

    if not no_exec:
        execute_file = args.executefile[0] if args.executefile else None
        weighted_sum_of_sanitizer_warnings = execute_program(program_dir_abs, execute_file, args.cmake, lines_of_code)
    else:
        weighted_sum_of_sanitizer_warnings = 0
        print(strings.WARNING_PROGRAM_EXECUTION_SKIPPED)

    weighted_warning_rate = (weighted_sum_of_compiler_warnings + weighted_sum_of_sanitizer_warnings) / lines_of_code
    score = scoring.calculate_compiler_and_sanitizer_score(weighted_warning_rate)
    scoring.print_score(score, 'Compiler + Sanitizer')

    if not exclude_infer:
        infer_compilation_status = compile_program_with_infer(args, excluded_paths)
    else:
        infer_compilation_status = False

    return score, infer_compilation_status


def static_analysis(program_dir_abs, source_files, lines_of_code, cpp, custom_asserts=None, cmake=False,
                    excluded_tools=None):  # TODO: maybe make the tools actual objects someday and remove this abomination of tool management
    """
    Run all the static analysis.
    :param program_dir_abs: The absolute path to the root directory of the target program.
    :param source_files: The lst of source files to analyze.
    :param lines_of_code: The lines of pure code count for the source_files.
    :param cpp: Whether C++ is used or not. True if C++, False if C.
    :param custom_asserts: A lst of custom assertions to be checked by the assertion check.
    :param cmake: Tells whether cmake is used or not (needed for infer)
    :param excluded_tools: Excludes the tools in the lst from the overall score
    :return: All the static analysis scores: assertion_score, cppcheck_score, clang_tidy_score,
    cyclomatic_complexity_score, warning_score, unique_score, kwstyle_score.
    """

    print(strings.RUN_STATIC_ANALYSIS_HEADER)
    print()

    used_tools = ["assertions", "infer", "clang_tidy", "lizard", "kwstyle", "cppcheck"]
    if not excluded_tools:
        excluded_tools = []

    for tool in excluded_tools:
        if tool in used_tools:
            used_tools.remove(tool)

    scores = []
    output = []
    tools = {}
    outs = {}
    instances = {}
    thread_pool = ThreadPool(processes=6)

    if "assertions" in used_tools:
        tools["assertions"] = (static_analysis_phase.check_assert_usage, (source_files, lines_of_code, custom_asserts))
    if "cppcheck" in used_tools:
        tools["cppcheck"] = (static_analysis_phase.run_cppcheck, (source_files, lines_of_code, cpp))
    if "clang_tidy" in used_tools:
        tools["clang_tidy"] = (static_analysis_phase.run_clang_tidy, (program_dir_abs, source_files, lines_of_code, cpp))
    if "lizard" in used_tools:
        tools["lizard"] = (static_analysis_phase.run_lizard, (source_files, ))
    if "kwstyle" in used_tools:
        tools["kwstyle"] = (static_analysis_phase.run_kwstyle, (source_files, lines_of_code))
    if "infer" in used_tools:
        tools["infer"] = (static_analysis_phase.run_infer_analysis, (program_dir_abs, lines_of_code, cmake))

    for key in tools:
        instances[key] = thread_pool.apply_async(tools[key][0], tools[key][1])

    for key in instances:
        outs[key] = instances[key].get()

    for key in outs:
        if key != "lizard":
            output.append((key, outs[key][0], outs[key][1], outs[key][2]))
        else:
            output.append(("lizard_cyclomatic_complexity", outs[key][0], "", outs[key][4]))
            output.append(("lizard_warnings", outs[key][1], "", outs[key][4]))
            output.append(("lizard_unique_code", outs[key][2], outs[key][3], outs[key][4]))

    for (name, score, log, stat) in output:
        if log:
            print(log)
        if stat:
            scores.append(score)
        else:
            print("{} failed".format(name))  # TODO: add string constant

    for tool in excluded_tools:
        print("{} was excluded from the score".format(tool))

    return scores


def add_badge_to_file(path, overall_score):
    #TODO: Clean and test this function
    """
    Experimental function to add a softwipe score badge to a github readme.
    :param path: path of the readme file
    :param overall_score: softwipe score received by the project
    """
    badge_string = strings.BADGE_LINK.format(round(overall_score, 1))

    lines = ""
    output = ""
    with open(path, 'r') as file:
        for line in file:
            lines += line

    if "[![Softwipe Score]" in lines:
        for line in lines.split("\n"):
            if "[![Softwipe Score]" in line:
                line = re.sub(r'\[!\[Softwipe Score\]\(([^\)\]]+)\)\]\(([^\)\]]+)\)', badge_string,
                              line.rstrip()) + "\n"
            output += line
    elif "[![" in lines:
        for line in lines.split("\n"):
            if "[![" in line and not badge_set:
                badge_set = True
                line += badge_string
            output += line
    else:
        for line in lines.split("\n"):
            output += line
            if not badge_set:
                badge_set = True
                output += badge_string + "\n"

    with open(path, 'w') as modified:
        modified.write(output)


def main():
    """
    Main function: Runs compilation, static analysis and prints results.
    """
    add_kwstyle_to_path_variable()

    # Allow the user to auto-install the dependencies by just running "./softwipe.py" without any arguments
    if len(sys.argv) == 1:
        automatic_tool_installation.check_if_all_required_tools_are_installed()

    args = parse_arguments()

    for argument in sys.argv:
        print(argument, end=" ")
    print()

    # Normal check for the dependencies
    if len(sys.argv) != 1:
        automatic_tool_installation.check_if_all_required_tools_are_installed()

    add_user_paths_to_path_variable(args)

    if not args.allow_running_as_root:
        warn_if_user_is_root()

    cpp = args.cpp
    cmake = args.cmake
    program_dir_abs = os.path.abspath(args.programdir)
    exclude = args.exclude[0] if args.exclude else None
    excluded_paths = util.get_excluded_paths(program_dir_abs, exclude)
    custom_asserts = args.custom_assert[0].split(',') if args.custom_assert else None

    source_files = util.find_all_source_files(program_dir_abs, excluded_paths)
    lines_of_code = util.count_lines_of_code(source_files)

    excluded_tools = []
    all_scores = []

    if not args.exclude_compilation:
        compiler_and_sanitizer_score, infer_compilation_status = compile_and_execute_program_with_sanitizers(
            args, lines_of_code, program_dir_abs, cpp, excluded_paths, args.no_execution, exclude_infer=args.exclude_infer)
        if not infer_compilation_status:
            excluded_tools.append('infer')
        all_scores.append(compiler_and_sanitizer_score)
    else:
        excluded_tools.append('compiler_and_sanitizer')
        excluded_tools.append('infer')

    if args.exclude_assertions:
        excluded_tools.append('assertions')
    if args.exclude_clang_tidy:
        excluded_tools.append('clang_tidy')
    if args.exclude_cppcheck:
        excluded_tools.append('cppcheck')
    if args.exclude_lizard:
        excluded_tools.append('lizard')
    if args.exclude_kwstyle:
        excluded_tools.append('kwstyle')
    if args.exclude_infer:
        excluded_tools.append('infer')

    all_scores.extend(static_analysis(program_dir_abs, source_files, lines_of_code, cpp, custom_asserts,
                                      cmake=cmake, excluded_tools=excluded_tools))

    overall_score = scoring.average_score(all_scores)

    print()
    scoring.print_score(overall_score, 'Overall program absolute')

    if args.add_badge:
        add_badge_to_file(args.add_badge[0], overall_score)
        print("Added badge to file {}".format(args.add_badge[0]))


if __name__ == "__main__":
    main()
